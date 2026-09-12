import datetime
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.serving import make_server as make_wsgi_server
import yt_dlp
from yt_dlp.extractor import gen_extractor_classes

from app_version import APP_VERSION
import updater


FROZEN = getattr(sys, "frozen", False)

# Код и вшитые ресурсы (шаблоны, ffmpeg). В собранном приложении это
# каталог PyInstaller (_internal рядом с exe) — он только для чтения.
RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Имя папки для скачанных видео в профиле пользователя.
DOWNLOAD_DIR_NAME = "Video Downloader"


def default_download_dir():
    """Куда складывать скачанное.

    В собранном приложении писать рядом с exe нельзя (каталог программы
    перезаписывается при обновлении и может быть закрыт на запись), поэтому
    файлы уходят в профиль пользователя: их видно в проводнике, они
    переживают обновление и удаление программы. Из исходников работаем
    как раньше — папка downloads рядом с app.py.
    """
    if not FROZEN:
        return os.path.join(BASE_DIR, "downloads")
    videos = os.path.join(os.path.expanduser("~"), "Videos")
    if os.path.isdir(videos):
        return os.path.join(videos, DOWNLOAD_DIR_NAME)
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                        "VideoDownloader", "downloads")


def current_download_dir():
    """Куда качаем сейчас: выбор пользователя или папка по умолчанию.

    Папку создаём при каждом обращении: её могли удалить или переименовать
    между запусками, а падать из-за этого приложение не должно.
    """
    saved = read_settings()["download_dir"]
    path = saved if saved else default_download_dir()
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = default_download_dir()
        os.makedirs(path, exist_ok=True)
    return path


os.makedirs(default_download_dir(), exist_ok=True)

# Шаблоны ищем в RESOURCE_DIR: в собранном виде они лежат внутри _internal,
# а не рядом с exe.
app = Flask(__name__, template_folder=os.path.join(RESOURCE_DIR, "templates"))

# Сюда desktop.py кладёт функцию закрытия окна: сервер сам себя не гасит,
# а после запуска установщика приложение должно уйти.
shutdown_callback = None

# Сюда desktop.py кладёт функцию показа системного диалога выбора папки:
# сам Flask окна не имеет, а тянуть webview в app.py нельзя — из
# исходников в браузере его может не быть вовсе.
folder_dialog_callback = None

jobs = {}
jobs_lock = threading.Lock()

# Рекламные/трекинговые параметры — к самому видео отношения не имеют.
# Если их не убрать, yt-dlp принимает хвост строки запроса за id видео
# и пишет в ошибку что-то вроде "?utm_source=newsletter".
TRACKING_PARAMS = {
    "yclid", "ysclid", "gclid", "fbclid", "igshid", "_openstat", "etext",
}

# yt-dlp раскрашивает свои ошибки для консоли; в браузере эти коды
# выглядят как мусор вида "[0;31mERROR:[0m".
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# По этим хвостам узнаём недокачанное: .part/.ytdl — обрывки загрузки,
# .temp.<ext> — файл склейки ffmpeg, .f<цифры>.<ext> — отдельные дорожки
# видео и звука до объединения. Готовое видео таких хвостов не имеет.
INCOMPLETE_RE = re.compile(r"\.(part|ytdl)$|\.temp\.[^.]+$|\.f\d+\.[^.]+$", re.IGNORECASE)


def is_incomplete_artifact(filename):
    """Обрывок незавершённой загрузки, а не готовое видео."""
    return bool(INCOMPLETE_RE.search(filename))


# Сколько запись о завершённой задаче висит в памяти, прежде чем её убрать.
# Речь только про запись — скачанные файлы остаются на диске навсегда.
# Ссылка на файл после этого продолжает работать: /api/file отдаёт его
# по имени из папки downloads, а не по номеру задачи.
JOB_TTL_SECONDS = 2 * 60 * 60
CLEANUP_INTERVAL_SECONDS = 10 * 60

# Потолок на размер файла. None — без ограничения (по умолчанию).
# Если когда-нибудь понадобится предохранитель — поставьте сюда байты,
# например 4 * 1024 ** 3, и проверка включится сама.
MAX_FILESIZE_BYTES = None

# Запас свободного места. Это не про размер видео, а про то, чтобы
# не забить диск под ноль на середине большой загрузки.
MIN_FREE_DISK_BYTES = 2 * 1024 ** 3

# Что показываем в списке качества и сколько это примерно весит.
# Цифры замерены на обычных роликах YouTube (H.264 + AAC): разброс большой,
# потому и диапазон — 60fps и вертикальное видео весят заметно больше.
QUALITY_OPTIONS = (
    (1080, "1080p — примерно 15–30 МБ на минуту"),
    (720, "720p — примерно 8–15 МБ на минуту"),
    (480, "480p — примерно 3–6 МБ на минуту"),
)

# Список допустимых значений держим одним источником со списком в интерфейсе:
# иначе рано или поздно в них разъедятся варианты.
ALLOWED_HEIGHTS = tuple(height for height, _ in QUALITY_OPTIONS)

# Качество по умолчанию. 1080p в H.264 — это около 25 МБ на минуту,
# для «скачать и посмотреть» это дорого, поэтому по умолчанию 720p.
TARGET_HEIGHT = 720

# Где запоминается выбор качества. Браузерное хранилище тут не годится:
# окно работает в приватном профиле, а порт при каждом запуске новый —
# для страницы это каждый раз новый источник, и хранилище всегда пустое.
SETTINGS_PATH = (os.path.join(BASE_DIR, "settings.json") if not FROZEN else
                 os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                              "VideoDownloader", "settings.json"))

# Журнал загрузок лежит рядом с настройками: в собранном виде это
# %LOCALAPPDATA%, из исходников — папка проекта.
HISTORY_PATH = os.path.join(os.path.dirname(SETTINGS_PATH), "history.json")

# Сколько записей журнала храним. Речь только про записи: файлы на диске
# не удаляются, даже когда запись о них выпала из журнала.
HISTORY_LIMIT = 200

DEFAULT_SETTINGS = {
    "target_height": TARGET_HEIGHT,
    "download_dir": None,
    "auto_update": True,
}

# ffmpeg не обязан стоять в системе: достаточно положить ffmpeg.exe в папку
# bin рядом с app.py — прав администратора для этого не нужно. В собранном
# приложении эта же папка вшита в дистрибутив, искать ничего не надо.
LOCAL_FFMPEG_DIR = os.path.join(RESOURCE_DIR, "bin")


def human_size(num_bytes):
    """Байты в человекочитаемый вид: 1536 -> '1.5 КБ'."""
    if not num_bytes:
        return "0 Б"
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ", "ПБ"):
        if abs(num_bytes) < 1024 or unit == "ПБ":
            return f"{num_bytes:.0f} {unit}" if unit == "Б" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024


def ffmpeg_path():
    """Путь к ffmpeg: сначала папка bin рядом с проектом, потом PATH.

    Ищем каждый раз, а не один раз при старте: иначе после установки
    ffmpeg пришлось бы перезапускать сервис, чтобы поднялось качество,
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
    return [f"res:{height or TARGET_HEIGHT}", "vcodec:h264", "acodec:aac"]


def normalize_height(value):
    """Приводит присланное качество к допустимому.

    Чужое значение (опечатка в запросе, открытая со вчера страница,
    «а давайте 2160») не должно ни ронять запрос, ни втихую качать 4K:
    берём значение по умолчанию.
    """
    try:
        height = int(value)
    except (TypeError, ValueError):
        return TARGET_HEIGHT
    return height if height in ALLOWED_HEIGHTS else TARGET_HEIGHT


def read_settings():
    """Все настройки одним словарём.

    Отсутствующие и мусорные значения заменяются умолчаниями поштучно:
    испорченный флаг обновлений не должен обнулять выбранное качество.
    """
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = None

    if not isinstance(data, dict):
        data = {}

    download_dir = data.get("download_dir")
    if not isinstance(download_dir, str) or not download_dir.strip():
        download_dir = None

    auto_update = data.get("auto_update")
    if not isinstance(auto_update, bool):
        auto_update = True

    return {
        "target_height": normalize_height(data.get("target_height")),
        "download_dir": download_dir,
        "auto_update": auto_update,
    }


def write_settings(**changes):
    """Дописывает переданные ключи, не теряя остальные."""
    try:
        settings = read_settings()
        settings.update(changes)
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump(settings, fh)
    except OSError as e:
        print(f"[настройки] не сохранились: {e}")


def read_saved_height():
    return read_settings()["target_height"]


def write_saved_height(height):
    write_settings(target_height=height)


def read_auto_update():
    return read_settings()["auto_update"]


def read_history():
    """Записи журнала. Испорченный файл — то же, что пустой журнал."""
    try:
        with open(HISTORY_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def write_history(items):
    try:
        os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
        with open(HISTORY_PATH, "w", encoding="utf-8") as fh:
            json.dump({"items": items[:HISTORY_LIMIT]}, fh)
    except OSError as e:
        print(f"[история] не сохранилась: {e}")


def history_add(record):
    """Кладёт запись первой, вытесняя прежнюю запись про тот же файл."""
    items = [item for item in read_history() if item.get("filename") != record["filename"]]
    items.insert(0, record)
    write_history(items)


def history_forget(filename):
    """Убирает запись о файле. Файл на диске не трогает."""
    items = [item for item in read_history() if item.get("filename") != filename]
    write_history(items)


def display_name(filename):
    """Имя файла без служебного префикса задачи (32 hex и подчёркивание)."""
    if not filename:
        return filename
    stripped = re.sub(r"^[0-9a-f]{32}_", "", filename)
    return stripped or filename


def human_when(timestamp):
    """'сегодня' / 'вчера' / '03.02.2026' — по местной дате."""
    day = datetime.date.fromtimestamp(timestamp)
    today = datetime.date.today()
    if day == today:
        return "сегодня"
    if day == today - datetime.timedelta(days=1):
        return "вчера"
    return day.strftime("%d.%m.%Y")


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


def humanize_error(url, raw_error, is_generic):
    """Переводит техническую ошибку yt-dlp в понятное объяснение.

    Возвращает (текст, вид) — вид нужен интерфейсу, чтобы выбрать цвет
    блока ошибки (красный/жёлтый) и не разбирать текст на глаз.
    """
    host = urlparse(url).netloc or url
    text = ANSI_RE.sub("", str(raw_error))

    if "HTTP Error 404" in text:
        if is_generic:
            return (
                f"Сайт {host} не поддерживается напрямую, и страница по ссылке не открылась (404). "
                "Обычно так бывает, если ссылка ведёт на страницу-обёртку или уже устарела. "
                "Нужна ссылка на само видео (YouTube, VK, Rutube и т.п.).",
                "not_found",
            )
        return f"Страница по ссылке не найдена (404) — проверьте ссылку на {host}.", "not_found"

    if "HTTP Error 403" in text or "Forbidden" in text:
        return (f"Сайт {host} закрыл доступ (403) — вероятно, ссылка работает только в браузере или нужен вход.",
                "forbidden")

    if "Unsupported URL" in text:
        return f"yt-dlp не умеет скачивать с {host}.", "unsupported"

    if "DRM" in text:
        return "Видео защищено DRM — скачать его нельзя.", "drm"

    if "No video formats found" in text or "Unable to extract" in text:
        return (
            f"На странице {host} не нашлось видеофайла. "
            "Часто плеер подгружается скриптом — тогда нужна прямая ссылка на видео, а не на страницу с ним.",
            "no_formats",
        )

    return f"Не удалось скачать видео с {host}.", "generic"


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


def known_dirs():
    """Текущая папка загрузок плюс те, где лежат файлы из журнала.

    После смены папки старые файлы никуда не делись — ссылка на них и
    «показать в папке» обязаны продолжать работать.
    """
    dirs = [current_download_dir()]
    seen = {os.path.normcase(os.path.abspath(dirs[0]))}
    for item in read_history():
        directory = item.get("dir")
        if not directory or not os.path.isdir(directory):
            continue
        key = os.path.normcase(os.path.abspath(directory))
        if key in seen:
            continue
        seen.add(key)
        dirs.append(directory)
    return dirs


def resolve_download_file(filename):
    """Путь к файлу по имени или None.

    Имя всегда сводится к basename: `<path:filename>` в маршруте пропускает
    сегменты вида ../, и без basename можно уйти за пределы папки загрузок.
    """
    safe_name = os.path.basename(filename)
    for directory in known_dirs():
        candidate = os.path.join(directory, safe_name)
        if os.path.isfile(candidate):
            return candidate
    return None


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
        print(f"[уборка] записей о задачах: {len(removed_jobs)} (файлы на диске сохранены)")
    return removed_jobs


def janitor_loop():
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            sweep_once()
        except Exception as e:
            print(f"[уборка] сорвалась: {e!r}")


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

    height = normalize_height(height)
    download_dir = current_download_dir()
    free = shutil.disk_usage(download_dir).free
    if free < MIN_FREE_DISK_BYTES:
        finish_job(
            job_id,
            status="error",
            error=f"Мало места на диске: свободно {human_size(free)}, "
                  f"нужно хотя бы {human_size(MIN_FREE_DISK_BYTES)}.",
            error_kind="disk",
        )
        return

    ie_key = extractor_key(url)
    print(f"[{job_id}] экстрактор: {ie_key} | качество: {height}p | ссылка: {url}")

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
                    history_add({
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
                error = (f"Видео весит {human_size(size)} — это больше лимита "
                         f"({human_size(MAX_FILESIZE_BYTES)}).")
                kind = "too_big"
            else:
                error = "yt-dlp не сохранил файл — скачивание не состоялось."
                kind = "generic"
            print(f"[{job_id}] файла нет после загрузки: {os.path.basename(filename)}")
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
        history_add({
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
            cancel_dir = (job.get("dir") if job else None) or current_download_dir()
        try:
            for name in os.listdir(cancel_dir):
                if name in cancel_snapshot or is_incomplete_artifact(name):
                    continue
                path = os.path.join(cancel_dir, name)
                if os.path.isfile(path):
                    history_add({
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
            weight = f"весит {human_size(size)} — это " if size else ""
            finish_job(
                job_id,
                status="error",
                error=f"Видео {weight}больше лимита ({human_size(MAX_FILESIZE_BYTES)}).",
                error_kind="too_big",
            )
        else:
            finish_job(job_id, status="cancelled")
    except yt_dlp.utils.DownloadError as e:
        cleanup_job_files(job_id)
        print(f"[{job_id}] yt-dlp: {e}")
        error, kind = humanize_error(url, e, ie_key == "Generic")
        finish_job(
            job_id,
            status="error",
            error=error,
            error_kind=kind,
            error_detail=ANSI_RE.sub("", str(e)),
        )
    except Exception as e:
        cleanup_job_files(job_id)
        print(f"[{job_id}] неожиданная ошибка: {e!r}")
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


@app.route("/")
def index():
    settings = read_settings()
    return render_template(
        "index.html",
        ffmpeg_available=ffmpeg_available(),
        max_filesize=human_size(MAX_FILESIZE_BYTES) if MAX_FILESIZE_BYTES else None,
        target_height=TARGET_HEIGHT,
        quality_options=QUALITY_OPTIONS,
        selected_height=settings["target_height"],
        app_version=APP_VERSION,
        desktop_mode=FROZEN,
        download_dir=current_download_dir(),
        auto_update=settings["auto_update"],
    )


@app.route("/api/download", methods=["POST"])
def download():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "Вставьте ссылку на видео"}), 400

    # Качество, которого нет в списке, молча заменяется на значение по
    # умолчанию: запрос не роняем, но и в 4K втихую не уходим.
    height = normalize_height(data.get("quality"))
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "status": "starting",
            "progress": 0,
            "downloaded_bytes": 0,
            "total_bytes": None,
            "speed": None,
            "eta": None,
            "filename": None,
            "title": None,
            "error": None,
            "error_detail": None,
            "error_kind": None,
            "abort_reason": None,
            "abort_size": None,
            "url": url,
            "height": height,
            "current_name": None,
            "playlist_index": None,
            "playlist_count": None,
            "dir_snapshot": None,
            "dir": None,
            "created_at": time.time(),
            "finished_at": None,
            "cancel_event": threading.Event(),
        }

    thread = threading.Thread(target=download_worker, args=(job_id, url, height), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/progress/<job_id>")
def progress(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Задача не найдена"}), 404
        return jsonify(public_job(job))


@app.route("/api/cancel/<job_id>", methods=["POST"])
def cancel(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Задача не найдена"}), 404
        if job["status"] in ("starting", "downloading"):
            job["status"] = "cancelling"
            job["cancel_event"].set()
    return jsonify({"ok": True})


@app.route("/api/file/<path:filename>")
def get_file(filename):
    file_path = resolve_download_file(filename)
    if file_path is None:
        return jsonify({"error": "Файл не найден"}), 404

    return send_from_directory(os.path.dirname(file_path), os.path.basename(file_path),
                                as_attachment=True)


@app.route("/api/quality", methods=["POST"])
def set_quality():
    """Запоминает выбор качества.

    Отдельный роут, а не сохранение внутри /api/download: выбор должен
    пережить перезапуск, даже если после него ничего не качали.
    """
    data = request.get_json(silent=True) or {}
    height = normalize_height(data.get("quality"))
    write_saved_height(height)
    return jsonify({"quality": height})


@app.route("/api/auto-update", methods=["POST"])
def set_auto_update():
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))
    write_settings(auto_update=enabled)
    # Включили — проверка стартует сразу, без перезапуска приложения.
    if enabled:
        updater.start_check_async()
    return jsonify({"auto_update": enabled})


@app.route("/api/update")
def update_status():
    # Выключённая проверка — не «нет обновлений», а «не спрашивали»:
    # интерфейс на это состояние просто молчит.
    if not read_auto_update():
        return jsonify({**updater.get_state(), "state": "disabled"})
    return jsonify(updater.get_state())


@app.route("/api/update/install", methods=["POST"])
def update_install():
    if not updater.start_install(shutdown_callback):
        return jsonify(updater.get_state()), 409
    return jsonify(updater.get_state())


@app.route("/api/open-folder/<path:filename>", methods=["POST"])
def open_folder(filename):
    """Показывает скачанный файл в проводнике.

    В окне приложения ссылка на файл бесполезна: WebView2 блокирует
    скачивание, и клик по ней просто ничего не делает. Файл уже лежит
    на диске, поэтому открываем папку с ним.
    """
    file_path = resolve_download_file(filename)
    if file_path is None:
        return jsonify({"error": "Файл не найден"}), 404

    try:
        # Запятая после /select — часть синтаксиса explorer, не опечатка.
        subprocess.Popen(["explorer", f"/select,{file_path}"])
    except OSError as e:
        return jsonify({"error": "Не удалось открыть папку с файлом",
                        "error_detail": f"{type(e).__name__}: {e}"}), 500

    return jsonify({"ok": True})


@app.route("/api/download-dir", methods=["POST"])
def set_download_dir():
    with jobs_lock:
        busy = any(job["status"] in ("starting", "downloading", "cancelling")
                    for job in jobs.values())
    if busy:
        return jsonify({"error": "Идёт загрузка — смените папку после её окончания."}), 409

    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"error": "Укажите папку для загрузок."}), 400
    if not os.path.isabs(path):
        return jsonify({"error": "Нужен полный путь к папке, например D:\\Видео."}), 400
    if os.path.exists(path) and not os.path.isdir(path):
        return jsonify({"error": "По этому пути лежит файл, а не папка."}), 400

    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        return jsonify({"error": "Не удалось создать папку — проверьте путь и права.",
                        "error_detail": f"{type(e).__name__}: {e}"}), 400

    probe = os.path.join(path, ".vd_write_test")
    try:
        with open(probe, "wb") as fh:
            fh.write(b"x")
        os.remove(probe)
    except OSError:
        return jsonify({"error": "В эту папку нельзя писать — выберите другую."}), 400

    write_settings(download_dir=path)
    return jsonify({"download_dir": path})


@app.route("/api/browse-folder", methods=["POST"])
def browse_folder():
    if folder_dialog_callback is None:
        return jsonify({"error": "Выбор папки доступен только в приложении. Впишите путь вручную."}), 409

    try:
        path = folder_dialog_callback()
    except Exception as e:
        return jsonify({"error": "Не удалось открыть диалог выбора папки.",
                        "error_detail": f"{type(e).__name__}: {e}"}), 500

    if not path:
        return jsonify({"cancelled": True})
    return jsonify({"path": path})


@app.route("/api/history")
def history():
    with jobs_lock:
        snapshot = [dict(job, job_id=job_id) for job_id, job in jobs.items()]

    items = []

    for job in snapshot:
        if job["status"] in ("starting", "downloading", "cancelling"):
            items.append({
                "kind": "active",
                "job_id": job["job_id"],
                "title": display_name(job.get("current_name")) if job.get("current_name") else "Загрузка…",
                "progress": job.get("progress"),
                "speed": job.get("speed"),
            })
        elif job["status"] == "cancelled":
            name = job.get("current_name")
            items.append({
                "kind": "cancelled",
                "job_id": job["job_id"],
                "title": display_name(name) if name else "Загрузка остановлена",
                "url": job.get("url"),
                "height": job.get("height"),
            })

    history_items = read_history()
    by_filename = {item["filename"]: item for item in history_items}

    seen_files = set()
    done = []
    for directory in known_dirs():
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if name.startswith("."):
                continue
            if name.split(".")[-1].lower() == "json":
                continue
            if is_incomplete_artifact(name):
                continue
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            if name in seen_files:
                continue
            seen_files.add(name)

            record = by_filename.get(name)
            if record:
                title = record.get("title") or display_name(name)
                height = record.get("height")
                url = record.get("url")
                finished_at = record.get("finished_at") or os.path.getmtime(path)
            else:
                title = display_name(name)
                height = None
                url = None
                finished_at = os.path.getmtime(path)

            size = os.path.getsize(path)
            done.append({
                "kind": "done",
                "filename": name,
                "title": title,
                "height": height,
                "size": size,
                "size_text": human_size(size),
                "finished_at": finished_at,
                "when": human_when(finished_at),
                "url": url,
            })

    done.sort(key=lambda item: item["finished_at"], reverse=True)
    items.extend(done)
    return jsonify({"items": items})


@app.route("/api/history/delete/<path:filename>", methods=["POST"])
def history_delete(filename):
    """Удаляет скачанный файл по явной команде пользователя.

    Единственное место в проекте, где файл пользователя удаляется намеренно:
    всё остальное (уборщик, TTL) чистит только записи в памяти.
    """
    path = resolve_download_file(filename)
    if path is None:
        return jsonify({"error": "Файл не найден"}), 404

    try:
        os.remove(path)
    except OSError as e:
        return jsonify({"error": "Не удалось удалить файл — возможно, он открыт в другой программе.",
                        "error_detail": f"{type(e).__name__}: {e}"}), 409

    history_forget(os.path.basename(path))
    return jsonify({"ok": True})


def create_server(host="127.0.0.1", port=0):
    """Поднимает сервер на свободном порту.

    Порт 0 значит «дай любой свободный»: жёсткий 5000 в десктопном
    приложении рано или поздно окажется занят чужой программой. Реальный
    номер потом читается из server.server_port.
    """
    return make_wsgi_server(host, port, app, threaded=True)


if __name__ == "__main__":
    # Запуск из исходников в браузере — как раньше: порт 5000 и debug,
    # чтобы правки в index.html подхватывались без перезапуска.
    # Десктопный запуск живёт в desktop.py.
    if read_auto_update():
        updater.start_check_async()
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
