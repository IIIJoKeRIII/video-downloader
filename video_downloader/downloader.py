"""Задачи загрузки: выбор формата, скачивание, отмена, уборка обрывков."""
import logging
import os
import re
import shutil
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import yt_dlp
from yt_dlp.extractor import gen_extractor_classes

from video_downloader import errors, storage

log = logging.getLogger(__name__)

# Рекламные/трекинговые параметры — к самому видео отношения не имеют.
# Если их не убрать, yt-dlp принимает хвост строки запроса за id видео
# и пишет в ошибку что-то вроде "?utm_source=newsletter".
TRACKING_PARAMS = {
    "yclid", "ysclid", "gclid", "fbclid", "igshid", "_openstat", "etext",
}

# По этим хвостам узнаём недокачанное: .part/.ytdl — обрывки загрузки,
# .temp.<ext> — файл склейки ffmpeg, .f<цифры>.<ext> — отдельные дорожки
# видео и звука до объединения. Готовое видео таких хвостов не имеет.
INCOMPLETE_RE = re.compile(r"\.(part|ytdl)$|\.temp\.[^.]+$|\.f\d+\.[^.]+$", re.IGNORECASE)

# Сколько запись о завершённой задаче висит в памяти, прежде чем её убрать.
# Речь только про запись — скачанные файлы остаются на диске навсегда,
# и «показать в папке» продолжает их находить: поиск идёт по имени файла,
# а не по номеру задачи.
JOB_TTL_SECONDS = 2 * 60 * 60
CLEANUP_INTERVAL_SECONDS = 10 * 60

# Потолок на размер файла. None — без ограничения (по умолчанию).
# Если когда-нибудь понадобится предохранитель — поставьте сюда байты,
# например 4 * 1024 ** 3, и проверка включится сама.
MAX_FILESIZE_BYTES = None

# Запас свободного места. Это не про размер видео, а про то, чтобы
# не забить диск под ноль на середине большой загрузки.
MIN_FREE_DISK_BYTES = 2 * 1024 ** 3

# ffmpeg не обязан стоять в системе: достаточно положить ffmpeg.exe в папку
# bin в корне проекта — прав администратора для этого не нужно. В собранном
# приложении эта же папка вшита в дистрибутив, искать ничего не надо.
LOCAL_FFMPEG_DIR = os.path.join(storage.RESOURCE_DIR, "bin")

jobs = {}
jobs_lock = threading.Lock()

_janitor_started = False


def is_incomplete_artifact(filename):
    """Обрывок незавершённой загрузки, а не готовое видео."""
    return bool(INCOMPLETE_RE.search(filename))


def ffmpeg_path():
    """Путь к ffmpeg: сначала папка bin в корне проекта, потом PATH.

    Ищем каждый раз, а не один раз при старте: иначе после установки
    ffmpeg пришлось бы перезапускать приложение, чтобы поднялось качество,
    и было бы непонятно, почему всё ещё 720p.
    """
    local = os.path.join(LOCAL_FFMPEG_DIR, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if os.path.isfile(local):
        return local
    return shutil.which("ffmpeg")


def ffmpeg_available():
    return ffmpeg_path() is not None


def build_format():
    """Формула выбора качества. Цель — 1080p в H.264.

    1080p YouTube отдаёт раздельными дорожками: видео без звука и звук
    отдельно. Склеить их может только ffmpeg. Без него доступны лишь
    готовые файлы со встроенным звуком, а там потолок сильно ниже.

    Кодек просим именно avc1 (H.264) с звуком mp4a (AAC). Само по себе
    «лучшее видео» на YouTube — это обычно av01 (AV1): он эффективнее,
    но встроенный плеер Windows без расширения из Store его не играет.
    H.264 чуть крупнее по размеру, зато открывается везде без плясок.
    """
    if ffmpeg_available():
        return "bestvideo+bestaudio/best"
    return "best"


def build_format_sort(height=None):
    """Порядок предпочтений при выборе потока.

    Ограничение по разрешению задаём через res, а не через height:
    у yt-dlp res — это min(ширина, высота), то есть короткая сторона.
    Фильтр по height ломается на вертикальном видео (Reels, Shorts,
    истории): там 1080x1920, высота 1920, и «height<=1080» вместо
    честного 1080p выдаёт огрызок 480x854.

    Кодек указываем предпочтением, а не жёстким фильтром: H.264 берём,
    когда он есть, но если у ролика только AV1 — качаем AV1, а не падаем.
    """
    return [f"res:{height or storage.TARGET_HEIGHT}", "vcodec:h264", "acodec:aac"]


def normalize_url(url):
    """Убирает из ссылки трекинговые параметры (utm_* и подобные)."""
    url = url.strip().strip("<>").strip()
    parts = urlparse(url)
    if not parts.query:
        return url

    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    ]
    return urlunparse(parts._replace(query=urlencode(kept)))


def extractor_key(url):
    """Какой экстрактор yt-dlp возьмёт для ссылки.

    "Generic" означает, что отдельной поддержки сайта нет: yt-dlp просто
    скачает HTML страницы и попробует найти в нём видео.
    """
    for extractor in gen_extractor_classes():
        if extractor.suitable(url):
            return extractor.ie_key()
    return "Generic"


def cleanup_job_files(job_id):
    """Убирает обрывки задачи: недокачанное и промежуточные дорожки.

    Готовые видео не трогает никогда — в том числе те, что успели
    докачаться из плейлиста до отмены. Файлы, лежавшие в папке до старта
    задачи, тоже неприкосновенны: снимок папки снимается перед загрузкой.
    """
    with jobs_lock:
        job = jobs.get(job_id)
        snapshot = job.get("dir_snapshot") if job else None
        directory = job.get("dir") if job else None

    # Записи о задаче нет — значит и снимка нет, и отличить свой обрывок
    # от чужого файла нельзя. В таком случае безопаснее не трогать ничего.
    if snapshot is None or not directory:
        return

    try:
        names = os.listdir(directory)
    except OSError:
        return

    for name in names:
        if name in snapshot or not is_incomplete_artifact(name):
            continue
        try:
            os.remove(os.path.join(directory, name))
        except OSError:
            pass


def finish_job(job_id, **fields):
    """Переводит задачу в конечное состояние и ставит отметку времени.

    Задачи к этому моменту может уже не быть — её мог убрать уборщик,
    поэтому обращаемся через get(), а не по ключу.
    """
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return
        job.update(fields)
        job["finished_at"] = time.time()


def sweep_once(now=None):
    """Убирает из памяти записи о завершённых задачах.

    Скачанные файлы не трогает — они остаются на диске насовсем.
    Мусор от сорвавшихся загрузок подчищается отдельно, в момент
    ошибки или отмены (cleanup_job_files), а не по таймеру.
    """
    now = time.time() if now is None else now
    removed_jobs = []

    with jobs_lock:
        for job_id, job in list(jobs.items()):
            finished_at = job.get("finished_at")
            if finished_at and now - finished_at > JOB_TTL_SECONDS:
                del jobs[job_id]
                removed_jobs.append(job_id)

    if removed_jobs:
        log.info("[уборка] записей о задачах: %s (файлы на диске сохранены)", len(removed_jobs))
    return removed_jobs


def janitor_loop():
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            sweep_once()
        except Exception as e:
            log.exception("[уборка] сорвалась: %r", e)


def start_janitor():
    """Запускает уборщик записей один раз за жизнь процесса.

    Импорт модуля ничего не запускает: иначе каждый импорт и каждый
    прогон проверок плодил бы фоновые потоки.
    """
    global _janitor_started
    if _janitor_started:
        return
    _janitor_started = True
    threading.Thread(target=janitor_loop, daemon=True, name="janitor").start()


def build_ydl_opts(outtmpl, height, hook):
    """Настройки yt-dlp для одной загрузки.

    Вынесено отдельно, чтобы выбранное качество можно было проверить,
    не запуская настоящую загрузку.
    """
    ydl_opts = {
        "outtmpl": outtmpl,
        "format": build_format(),
        "format_sort": build_format_sort(height),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        # Обрыв связи не должен убивать всю загрузку: пробуем ещё,
        # а начатый файл продолжаем с места разрыва, а не с нуля.
        "retries": 5,
        "fragment_retries": 10,
        "socket_timeout": 30,
        "continuedl": True,
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
    }

    ffmpeg = ffmpeg_path()
    if ffmpeg:
        ydl_opts["merge_output_format"] = "mp4"
        ydl_opts["ffmpeg_location"] = ffmpeg
    return ydl_opts


def download_worker(job_id, url, height=None):
    url = normalize_url(url)

    height = storage.normalize_height(height)
    download_dir = storage.current_download_dir()
    free = shutil.disk_usage(download_dir).free
    if free < MIN_FREE_DISK_BYTES:
        finish_job(
            job_id,
            status="error",
            error=f"Мало места на диске: свободно {storage.human_size(free)}, "
                  f"нужно хотя бы {storage.human_size(MIN_FREE_DISK_BYTES)}.",
            error_kind="disk",
        )
        return

    ie_key = extractor_key(url)
    log.info("[%s] экстрактор: %s | качество: %sp | ссылка: %s", job_id, ie_key, height, url)

    # Имя файла — название видео как есть. Префикса задачи больше нет:
    # обрывки ищутся по снимку папки и хвостам имени (is_incomplete_artifact),
    # а не по маске job_id, и пользователю больше не достаётся
    # «f64202d6d3b0…__.mp4» вместо названия.
    outtmpl = os.path.join(download_dir, "%(title).120s.%(ext)s")

    # Что лежало в папке до начала задачи. Всё это — чужое: при уборке
    # обрывков такие файлы не трогаем, даже если имя похоже на обрывок.
    try:
        snapshot = set(os.listdir(download_dir))
    except OSError:
        snapshot = set()
    with jobs_lock:
        job = jobs.get(job_id)
        if job is not None:
            job["dir_snapshot"] = snapshot
            job["dir"] = download_dir

    def hook(d):
        with jobs_lock:
            job = jobs.get(job_id)
        if job is None:
            return
        if job["cancel_event"].is_set():
            raise yt_dlp.utils.DownloadCancelled("Остановлено пользователем")

        if d["status"] == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            progress = round(downloaded / total * 100, 1) if total else None
            info_dict = d.get("info_dict") or {}

            # Лимит (если включён) держим здесь, а не через max_filesize у
            # yt-dlp: тот при превышении молча пропускает загрузку — ни
            # исключения, ни размера, и наружу уходит «Готово» с
            # несуществующим файлом.
            if MAX_FILESIZE_BYTES and (total or downloaded) > MAX_FILESIZE_BYTES:
                with jobs_lock:
                    job["abort_reason"] = "too_big"
                    job["abort_size"] = total or downloaded
                raise yt_dlp.utils.DownloadCancelled("Превышен лимит размера")

            with jobs_lock:
                job.update({
                    "status": "downloading",
                    "downloaded_bytes": downloaded,
                    "total_bytes": total,
                    "progress": progress,
                    "speed": d.get("speed"),
                    "eta": d.get("eta"),
                    "current_name": os.path.basename(d.get("filename") or "") or None,
                    "playlist_index": info_dict.get("playlist_index"),
                    "playlist_count": info_dict.get("playlist_count") or info_dict.get("n_entries"),
                })
        elif d["status"] == "finished":
            with jobs_lock:
                job["progress"] = 100

    ydl_opts = build_ydl_opts(outtmpl, height, hook)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            entries = info.get("entries") if info.get("_type") == "playlist" else None
            if entries is not None:
                # Плейлист: файлов много, каждый — отдельная запись в истории.
                saved = []
                for entry in entries:
                    if not entry:
                        continue
                    entry_requested = (entry.get("requested_downloads") or [{}])[0]
                    entry_path = entry_requested.get("filepath")
                    if entry_path and os.path.isfile(entry_path):
                        saved.append((entry_path, entry))

                if not saved:
                    cleanup_job_files(job_id)
                    finish_job(job_id, status="error",
                               error="Из плейлиста не скачалось ни одного видео.",
                               error_kind="generic")
                    return

                for entry_path, entry in saved:
                    storage.history_add({
                        "filename": os.path.basename(entry_path),
                        "dir": os.path.dirname(entry_path),
                        "title": entry.get("title") or os.path.basename(entry_path),
                        "height": height,
                        "url": entry.get("webpage_url") or url,
                        "size": os.path.getsize(entry_path),
                        "finished_at": time.time(),
                    })

                first_path = saved[0][0]
                finish_job(
                    job_id,
                    status="finished",
                    progress=100,
                    filename=os.path.basename(first_path),
                    title=f"{info.get('title') or 'Плейлист'} — скачано {len(saved)} видео",
                )
                return

            # filepath — фактический путь после всех постобработок,
            # prepare_filename только запасной вариант.
            requested = (info.get("requested_downloads") or [{}])[0]
            filename = requested.get("filepath") or ydl.prepare_filename(info)

        # yt-dlp умеет молча пропустить загрузку (например, когда файл больше
        # max_filesize): исключения нет, info есть, а файла на диске нет.
        # Без этой проверки пользователь получал «Готово» и битую ссылку.
        if not os.path.isfile(filename):
            size = (requested.get("filesize") or requested.get("filesize_approx")
                    or info.get("filesize") or info.get("filesize_approx"))
            if MAX_FILESIZE_BYTES and size and size > MAX_FILESIZE_BYTES:
                error = (f"Видео весит {storage.human_size(size)} — это больше лимита "
                         f"({storage.human_size(MAX_FILESIZE_BYTES)}).")
                kind = "too_big"
            else:
                error = "yt-dlp не сохранил файл — скачивание не состоялось."
                kind = "generic"
            log.warning("[%s] файла нет после загрузки: %s", job_id, os.path.basename(filename))
            cleanup_job_files(job_id)
            finish_job(job_id, status="error", error=error, error_kind=kind,
                       error_detail=f"ожидался файл {os.path.basename(filename)}")
            return

        title = info.get("title") or os.path.basename(filename)
        finish_job(
            job_id,
            status="finished",
            progress=100,
            filename=os.path.basename(filename),
            title=title,
        )
        storage.history_add({
            "filename": os.path.basename(filename),
            "dir": os.path.dirname(filename),
            "title": title,
            "height": height,
            "url": url,
            "size": os.path.getsize(filename),
            "finished_at": time.time(),
        })
    except yt_dlp.utils.DownloadCancelled:
        cleanup_job_files(job_id)
        threading.Timer(2.0, cleanup_job_files, args=(job_id,)).start()

        # Уцелевшее после отмены — это докачанные видео плейлиста. Файлы
        # остаются, но записи о них нет: заносим, чтобы в истории было
        # видно качество, а не только имя файла.
        with jobs_lock:
            job = jobs.get(job_id)
            cancel_snapshot = (job.get("dir_snapshot") if job else None) or set()
            cancel_dir = (job.get("dir") if job else None) or storage.current_download_dir()
        try:
            for name in os.listdir(cancel_dir):
                if name in cancel_snapshot or is_incomplete_artifact(name):
                    continue
                path = os.path.join(cancel_dir, name)
                if os.path.isfile(path):
                    storage.history_add({
                        "filename": name,
                        "dir": cancel_dir,
                        "title": os.path.splitext(name)[0],
                        "height": height,
                        "url": url,
                        "size": os.path.getsize(path),
                        "finished_at": time.time(),
                    })
        except OSError:
            pass

        with jobs_lock:
            job = jobs.get(job_id)
            too_big = bool(job and job.get("abort_reason") == "too_big")
            size = job.get("abort_size") if job else None

        if too_big:
            weight = f"весит {storage.human_size(size)} — это " if size else ""
            finish_job(
                job_id,
                status="error",
                error=f"Видео {weight}больше лимита ({storage.human_size(MAX_FILESIZE_BYTES)}).",
                error_kind="too_big",
            )
        else:
            finish_job(job_id, status="cancelled")
    except yt_dlp.utils.DownloadError as e:
        cleanup_job_files(job_id)
        log.warning("[%s] yt-dlp: %s", job_id, e)
        error, kind = errors.humanize_error(url, e, ie_key == "Generic")
        finish_job(
            job_id,
            status="error",
            error=error,
            error_kind=kind,
            error_detail=errors.ANSI_RE.sub("", str(e)),
        )
    except Exception as e:
        cleanup_job_files(job_id)
        log.exception("[%s] неожиданная ошибка: %r", job_id, e)
        finish_job(
            job_id,
            status="error",
            error="Неожиданная ошибка при скачивании.",
            error_kind="generic",
            error_detail=f"{type(e).__name__}: {e}",
        )


def public_job(job):
    return {
        "status": job["status"],
        "progress": job["progress"],
        "downloaded_bytes": job["downloaded_bytes"],
        "total_bytes": job["total_bytes"],
        "speed": job["speed"],
        "eta": job["eta"],
        "filename": job["filename"],
        "title": job["title"],
        "error": job["error"],
        "error_detail": job["error_detail"],
        "error_kind": job.get("error_kind"),
        "url": job.get("url"),
        "height": job.get("height"),
        "current_name": job.get("current_name"),
        "playlist_index": job.get("playlist_index"),
        "playlist_count": job.get("playlist_count"),
    }
