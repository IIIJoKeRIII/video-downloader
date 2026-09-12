"""Проверки приложения. Интернет не нужен: поднимается локальный сайт-заглушка.

Запуск из корня проекта:
    python tests/smoke_test.py

Код возврата 0 — всё зелёное, 1 — есть падения.
Файлы, созданные тестом, удаляются; чужие файлы в downloads/ не трогаются.
"""
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote

# Корень считается от файла проверок, а не берётся из storage: проверка
# «пути из исходников» обязана поймать storage.PROJECT_DIR, указывающий
# на папку пакета.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from video_downloader import downloader, storage, updater  # noqa: E402
from video_downloader.api import Api  # noqa: E402
from video_downloader.version import APP_VERSION  # noqa: E402

PORT = 8765
SMALL = b"\x00" * (200 * 1024)
BIG = b"\x00" * (3 * 1024 * 1024)
INSTALLER = b"MZ" + b"\x00" * (200 * 1024)

EXPECTED_API = {
    "bootstrap", "start_download", "get_progress", "cancel", "set_quality",
    "set_auto_update", "get_update_state", "install_update", "reveal_file",
    "get_history", "delete_file", "choose_download_dir",
}

results = []
created_files = []


class Stub(BaseHTTPRequestHandler):
    """Отдаёт два «видео» и 404 на всё остальное."""

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path == "/releases/newer":
            body = json.dumps({
                "tag_name": "v99.0.0",
                "assets": [
                    {"name": "notes.txt",
                     "browser_download_url": f"http://127.0.0.1:{PORT}/notes.txt"},
                    {"name": "video-downloader-99.0.0-setup.exe",
                     "browser_download_url": f"http://127.0.0.1:{PORT}/setup.exe"},
                ],
            }).encode()
        elif path == "/releases/same":
            body = json.dumps({"tag_name": f"v{APP_VERSION}", "assets": []}).encode()
        elif path == "/setup.exe":
            body = INSTALLER
        else:
            body = {"/small.mp4": SMALL, "/big.mp4": BIG,
                    "/Тестовое видео.mp4": SMALL}.get(path)
        if body is None:
            self.send_error(404, "Not Found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def check(name, condition, extra=""):
    results.append(bool(condition))
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f" -> {extra}" if extra else ""))


def call(method, *args):
    """Вызов, как его сделает pywebview: результат обязан пережить json.dumps."""
    result = method(*args)
    json.dumps(result)
    return result


def quiet_api(**callbacks):
    """Api, который никогда не ходит в настоящий GitHub."""
    callbacks.setdefault("start_update_check", lambda: None)
    return Api(**callbacks)


def package_sources():
    """Тексты всех модулей пакета одной строкой."""
    package_dir = os.path.join(ROOT, "video_downloader")
    texts = []
    for name in sorted(os.listdir(package_dir)):
        if name.endswith(".py"):
            with open(os.path.join(package_dir, name), encoding="utf-8") as fh:
                texts.append(fh.read())
    return "\n".join(texts)


def run_job(api, url, timeout=60, quality=None):
    """Ставит задачу и ждёт конечного статуса."""
    job_id = call(api.start_download, url, quality)["job_id"]
    state = {}
    for _ in range(timeout * 10):
        state = call(api.get_progress, job_id)
        if state.get("status") in ("finished", "error", "cancelled"):
            break
        time.sleep(0.1)
    if state.get("filename"):
        created_files.append(os.path.join(storage.current_download_dir(), state["filename"]))
    return job_id, state


def main():
    print("=== импорт ничего не запускает ===")
    check("уборщик не стартовал при импорте",
          not any(t.name == "janitor" for t in threading.enumerate()))
    downloader.start_janitor()
    downloader.start_janitor()
    check("start_janitor запускает ровно один уборщик",
          sum(1 for t in threading.enumerate() if t.name == "janitor") == 1)

    server = HTTPServer(("127.0.0.1", PORT), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    update_checks = []
    api = Api(start_update_check=lambda: update_checks.append(True))
    base = f"http://127.0.0.1:{PORT}"

    print("\n=== выбор качества ===")
    fmt, srt = downloader.build_format(), downloader.build_format_sort()
    print(f"  ffmpeg: {downloader.ffmpeg_available()} | format: {fmt} | sort: {srt}")
    check("ограничение по res, а не по height",
          any(s.startswith("res:") for s in srt) and not any("height" in s for s in srt), srt)
    check("целевое разрешение из TARGET_HEIGHT", f"res:{storage.TARGET_HEIGHT}" in srt)
    check("H.264 в предпочтениях", "vcodec:h264" in srt)
    check("склейка потоков только при наличии ffmpeg",
          ("+bestaudio" in fmt) == downloader.ffmpeg_available(), fmt)

    print("\n=== разбор ссылок ===")
    check("трекинговые параметры срезаются",
          downloader.normalize_url("https://a.tld/v/?utm_referrer=www.kinopoisk.ru") == "https://a.tld/v/")
    check("полезные параметры сохраняются",
          downloader.normalize_url("https://www.youtube.com/watch?v=abc&t=42s&utm_source=x")
          == "https://www.youtube.com/watch?v=abc&t=42s")
    check("известный сайт получает свой экстрактор",
          downloader.extractor_key("https://vk.com/video-1_2") != "Generic")
    check("неизвестный сайт уходит в Generic",
          downloader.extractor_key(f"{base}/film/1/") == "Generic")

    print("\n=== размеры в человеческом виде ===")
    for value, want in [(0, "0 Б"), (512, "512 Б"), (1536, "1.5 КБ"), (4 * 1024 ** 3, "4.0 ГБ")]:
        check(f"{value} -> {want}", storage.human_size(value) == want, storage.human_size(value))

    print("\n=== скачивание ===")
    _, state = run_job(api, f"{base}/small.mp4")
    check("задача завершилась успехом", state["status"] == "finished",
          state.get("error") or state.get("error_detail"))
    check("файл появился на диске", bool(state["filename"])
          and os.path.isfile(os.path.join(storage.current_download_dir(), state["filename"])))

    print("\n=== ошибки понятны человеку ===")
    _, state = run_job(api, f"{base}/film/404/")
    check("статус error", state["status"] == "error", state.get("status"))
    check("текст объясняет причину", "404" in (state.get("error") or ""), state.get("error"))
    check("технические детали отдельным полем", bool(state.get("error_detail")))
    check("ANSI-коды вычищены", "\x1b" not in (state.get("error_detail") or ""))

    print("\n=== лимит размера (по умолчанию выключен) ===")
    check("MAX_FILESIZE_BYTES выключен", downloader.MAX_FILESIZE_BYTES is None, downloader.MAX_FILESIZE_BYTES)
    _, state = run_job(api, f"{base}/big.mp4")
    check("большой файл качается без препятствий", state["status"] == "finished", state.get("error"))

    saved = downloader.MAX_FILESIZE_BYTES
    downloader.MAX_FILESIZE_BYTES = 1024 * 1024
    # Имя файла не содержит id задачи — без удаления предыдущего "big.mp4"
    # yt-dlp увидит его на диске и молча пропустит скачивание, даже не
    # дойдя до проверки лимита в хуке.
    stale_big = os.path.join(storage.current_download_dir(), "big.mp4")
    if os.path.isfile(stale_big):
        os.remove(stale_big)
    job_id, state = run_job(api, f"{base}/big.mp4")
    check("включённый лимит останавливает загрузку", state["status"] == "error", state.get("error"))
    check("в тексте настоящий вес файла", "3.0 МБ" in (state.get("error") or ""), state.get("error"))
    check("обрывок не остался",
          not any(downloader.is_incomplete_artifact(n) and "big" in n.lower()
                  for n in os.listdir(storage.current_download_dir())))
    downloader.MAX_FILESIZE_BYTES = saved

    print("\n=== запас места на диске ===")
    saved_min = downloader.MIN_FREE_DISK_BYTES
    downloader.MIN_FREE_DISK_BYTES = 10 ** 18
    _, state = run_job(api, f"{base}/small.mp4")
    check("отказ до начала скачивания",
          state["status"] == "error" and "Мало места" in (state.get("error") or ""),
          state.get("error"))
    downloader.MIN_FREE_DISK_BYTES = saved_min

    print("\n=== is_incomplete_artifact: что считается обрывком ===")
    artifact_cases = [
        ("Видео.mp4.part", True),
        ("Видео.ytdl", True),
        ("Видео.temp.mp4", True),
        ("Видео.f299.mp4", True),
        ("Видео.f140.m4a", True),
        ("Видео.mp4", False),
        ("Обычное имя.mkv", False),
        ("f140.mp4", False),
    ]
    for name, expected in artifact_cases:
        check(f"{name!r} -> {expected}", downloader.is_incomplete_artifact(name) == expected)

    print("\n=== уборка обрывков: новая логика (по снимку папки, не по id задачи) ===")
    # Собственная временная папка, а не current_download_dir(): dir_snapshot
    # в этих проверках нарочно пустой, и если бы cleanup_job_files смотрела
    # в настоящую папку загрузок, под "обрывок" попали бы и чужие файлы,
    # которые лежали там до теста, но не в этом самом снимке.
    cleanup_dir = tempfile.mkdtemp(prefix="zzqa_cleanup_")
    try:
        cleanup_job_id = "zzqacleanupjob"
        ready_file = os.path.join(cleanup_dir, "zzqa_ready.mp4")
        broken_file = os.path.join(cleanup_dir, "zzqa_broken.mp4.part")
        with open(ready_file, "wb") as fh:
            fh.write(b"ready-bytes")
        with open(broken_file, "wb") as fh:
            fh.write(b"broken-bytes")
        with downloader.jobs_lock:
            # Снимок папки не содержит ни того, ни другого файла — оба
            # появились уже "во время" этой задачи.
            downloader.jobs[cleanup_job_id] = {"dir_snapshot": set(), "dir": cleanup_dir}
        downloader.cleanup_job_files(cleanup_job_id)
        check("докачанное видео пережило уборку", os.path.isfile(ready_file))
        check("обрывок (.part) удалён", not os.path.isfile(broken_file))
        with downloader.jobs_lock:
            downloader.jobs.pop(cleanup_job_id, None)

        alien_job_id = "zzqaalienjob"
        alien_file = os.path.join(cleanup_dir, "zzqa_alien.mp4.part")
        with open(alien_file, "wb") as fh:
            fh.write(b"alien-bytes")
        with downloader.jobs_lock:
            # На этот раз файл УЖЕ есть в снимке — он был в папке до старта
            # задачи, хотя имя и похоже на обрывок. Трогать нельзя.
            downloader.jobs[alien_job_id] = {"dir_snapshot": {"zzqa_alien.mp4.part"}, "dir": cleanup_dir}
        downloader.cleanup_job_files(alien_job_id)
        check("файл из снимка не тронут, даже похожий на обрывок", os.path.isfile(alien_file))
        with downloader.jobs_lock:
            downloader.jobs.pop(alien_job_id, None)

        try:
            downloader.cleanup_job_files("нет-такой-задачи-vообще")
            check("уборка без записи о задаче не падает и ничего не трогает", True)
        except Exception as exc:
            check("уборка без записи о задаче не падает и ничего не трогает", False, repr(exc))

        print("\n=== плейлист: отмена не удаляет уже докачанные видео ===")
        pl_job_id = "zzqaplaylistjob"
        pl_done_1 = os.path.join(cleanup_dir, "zzqa_pl_1.mp4")
        pl_done_2 = os.path.join(cleanup_dir, "zzqa_pl_2.mp4")
        pl_broken = os.path.join(cleanup_dir, "zzqa_pl_3.mp4.part")
        for path in (pl_done_1, pl_done_2, pl_broken):
            with open(path, "wb") as fh:
                fh.write(b"x")
        with downloader.jobs_lock:
            downloader.jobs[pl_job_id] = {"dir_snapshot": set(), "dir": cleanup_dir}
        downloader.cleanup_job_files(pl_job_id)
        check("первое докачанное видео плейлиста цело", os.path.isfile(pl_done_1))
        check("второе докачанное видео плейлиста цело", os.path.isfile(pl_done_2))
        check("недокачанное третье видео удалено", not os.path.isfile(pl_broken))
        with downloader.jobs_lock:
            downloader.jobs.pop(pl_job_id, None)
    finally:
        shutil.rmtree(cleanup_dir, ignore_errors=True)

    print("\n=== юникодные имена файлов ===")
    _, state = run_job(api, f"{base}/Тестовое видео.mp4")
    check("юникодное название доехало до файла",
          state["status"] == "finished" and "Тестовое видео" in (state.get("filename") or ""),
          state.get("filename"))
    check("файл реально на диске", bool(state.get("filename"))
          and os.path.isfile(os.path.join(storage.current_download_dir(), state["filename"])))

    print("\n=== плейлист: поля в public_job ===")
    check("у обычной задачи playlist_index/playlist_count пустые",
          state.get("playlist_index") is None and state.get("playlist_count") is None)

    print("\n=== уборка: записи убираются, файлы остаются ===")
    old_id, live_id = "zzqaoldjob", "zzqalivejob"
    old_file = os.path.join(storage.current_download_dir(), f"{old_id}_movie.mp4")
    live_file = os.path.join(storage.current_download_dir(), f"{live_id}_movie.mp4")
    for path in (old_file, live_file):
        with open(path, "wb") as fh:
            fh.write(b"x")
        created_files.append(path)

    stale = time.time() - downloader.JOB_TTL_SECONDS - 60
    with downloader.jobs_lock:
        downloader.jobs[old_id] = {"status": "finished", "finished_at": stale}
        downloader.jobs[live_id] = {"status": "downloading", "finished_at": None}

    removed = downloader.sweep_once()
    check("протухшая запись убрана из памяти", old_id in removed)
    check("СКАЧАННЫЙ ФАЙЛ ОСТАЛСЯ НА ДИСКЕ", os.path.isfile(old_file))
    check("незавершённая задача не тронута", live_id in downloader.jobs)
    check("её файл цел", os.path.isfile(live_file))
    found = storage.resolve_download_file(os.path.basename(old_file))
    check("файл находится по имени после уборки записи",
          found is not None and os.path.normcase(found) == os.path.normcase(old_file), found)

    with downloader.jobs_lock:
        downloader.jobs.pop(live_id, None)

    print("\n=== папка загрузок ===")
    saved_download_dir = storage.read_settings()["download_dir"]
    original_dir = storage.current_download_dir()
    new_dir = os.path.join(original_dir, "zzqa_dir_probe")

    def picker(path):
        return quiet_api(pick_folder=lambda: path)

    try:
        resp = call(picker(new_dir).choose_download_dir)
        check("смена папки принимается", resp["ok"] is True, resp)
        check("current_download_dir теперь новая папка",
              os.path.normcase(storage.current_download_dir()) == os.path.normcase(new_dir))

        _, state = run_job(api, f"{base}/small.mp4")
        check("загрузка идёт в новую папку", state["status"] == "finished"
              and os.path.isfile(os.path.join(new_dir, state["filename"])), state.get("filename"))

        check("относительный путь отклонён",
              call(picker("relative\\path").choose_download_dir)["ok"] is False)
        check("путь на существующий файл отклонён",
              call(picker(os.path.join(new_dir, state["filename"])).choose_download_dir)["ok"] is False)
        check("путь из пробелов отклонён",
              call(picker("   ").choose_download_dir)["ok"] is False)

        resp = call(picker(None).choose_download_dir)
        check("отмена диалога ничего не меняет",
              resp == {"ok": True, "cancelled": True}
              and os.path.normcase(storage.current_download_dir()) == os.path.normcase(new_dir), resp)

        with downloader.jobs_lock:
            downloader.jobs["zzqabusyjob"] = {"status": "downloading"}
        try:
            check("смена папки во время загрузки отклонена",
                  call(picker(original_dir).choose_download_dir)["ok"] is False)
        finally:
            with downloader.jobs_lock:
                downloader.jobs.pop("zzqabusyjob", None)

        check("без диалога — отказ", call(quiet_api().choose_download_dir)["ok"] is False)

        def broken_dialog():
            raise OSError("диалог сломан")

        resp = call(quiet_api(pick_folder=broken_dialog).choose_download_dir)
        check("сломанный диалог — отказ с подробностями",
              resp["ok"] is False and "диалог сломан" in (resp.get("error_detail") or ""), resp)
    finally:
        storage.write_settings(download_dir=saved_download_dir)
        check("папка вернулась к исходной",
              os.path.normcase(storage.current_download_dir()) == os.path.normcase(original_dir))
        shutil.rmtree(new_dir, ignore_errors=True)

    print("\n=== старая папка продолжает находиться после смены ===")
    # Файл лежит вне текущей папки, но известен через журнал — поиск по
    # имени обязан найти его и там, а не только в current_download_dir().
    outside_dir = os.path.join(original_dir, "zzqa_outside")
    os.makedirs(outside_dir, exist_ok=True)
    outside_file = os.path.join(outside_dir, "zzqa_outside_movie.mp4")
    with open(outside_file, "wb") as fh:
        fh.write(b"x")
    storage.history_add({
        "filename": os.path.basename(outside_file),
        "dir": outside_dir,
        "title": "outside movie",
        "height": 720,
        "url": "http://example.test/outside",
        "size": 1,
        "finished_at": time.time(),
    })
    try:
        check("файл из прежней папки виден в known_dirs", outside_dir in storage.known_dirs())
        found = storage.resolve_download_file(os.path.basename(outside_file))
        check("файл из прежней папки находится по имени",
              found is not None and os.path.normcase(found) == os.path.normcase(outside_file), found)
    finally:
        storage.history_forget(os.path.basename(outside_file))
        try:
            os.remove(outside_file)
        except OSError as exc:
            print(f"  (не удалось убрать {outside_file}: {exc})")
        try:
            os.rmdir(outside_dir)
        except OSError:
            pass

    print("\n=== история ===")
    _, state = run_job(api, f"{base}/small.mp4", quality=480)
    done_name = state["filename"]
    check("загрузка успешна", state["status"] == "finished", state.get("error"))
    try:
        items = call(api.get_history)["items"]
        entry = next((i for i in items if i.get("filename") == done_name), None)
        check("скачанное появилось в истории", entry is not None, items)
        check("у записи есть title/size_text/when",
              entry and entry.get("title") and entry.get("size_text") and entry.get("when"))
        check("качество из журнала", entry and entry.get("height") == 480, entry)

        check("display_name срезает префикс задачи",
              storage.display_name("0123456789abcdef0123456789abcdef_Кино.mp4") == "Кино.mp4")
        check("display_name не портит обычные имена",
              storage.display_name("Кино.mp4") == "Кино.mp4")

        check("human_when: сегодня", storage.human_when(time.time()) == "сегодня")
        check("human_when: вчера", storage.human_when(time.time() - 86400) == "вчера")

        orphan = os.path.join(storage.current_download_dir(), "zzqa_orphan.mp4")
        with open(orphan, "wb") as fh:
            fh.write(b"x")
        created_files.append(orphan)
        items = call(api.get_history)["items"]
        orphan_entry = next((i for i in items if i.get("filename") == "zzqa_orphan.mp4"), None)
        check("файл без записи в журнале виден по имени файла",
              orphan_entry is not None and orphan_entry["title"] == "zzqa_orphan.mp4", orphan_entry)

        active_job_id = "zzqahistjob"
        part_file = os.path.join(storage.current_download_dir(), "zzqa_active_video.mp4.part")
        with open(part_file, "wb") as fh:
            fh.write(b"x")
        created_files.append(part_file)
        with downloader.jobs_lock:
            downloader.jobs[active_job_id] = {"status": "downloading", "progress": 10, "speed": None,
                                              "current_name": None}
        items = call(api.get_history)["items"]
        with downloader.jobs_lock:
            downloader.jobs.pop(active_job_id, None)
        check("обрывок (.part) скрыт из готовых",
              not any(i.get("filename") == "zzqa_active_video.mp4.part" and i["kind"] == "done" for i in items))
        check("активная строка присутствует",
              any(i["kind"] == "active" and i["job_id"] == active_job_id for i in items))

        victim = os.path.join(storage.current_download_dir(), "zzqa_victim.mp4")
        bystander = os.path.join(storage.current_download_dir(), "zzqa_bystander.mp4")
        with open(victim, "wb") as fh:
            fh.write(b"victim-bytes")
        with open(bystander, "wb") as fh:
            fh.write(b"bystander-bytes")
        created_files.append(bystander)
        bystander_before = open(bystander, "rb").read()

        resp = call(api.delete_file, "zzqa_victim.mp4")
        check("удаление успешно", resp["ok"] is True, resp)
        check("файл удалён", not os.path.isfile(victim))
        check("соседний файл цел и не изменился",
              os.path.isfile(bystander) and open(bystander, "rb").read() == bystander_before)

        check("удаление несуществующего — отказ",
              call(api.delete_file, "zzqa_no_such_file.mp4")["ok"] is False)
        traversal_target = os.path.join(ROOT, "requirements.txt")
        before_target = open(traversal_target, "rb").read()
        resp = call(api.delete_file, "../requirements.txt")
        check("выход за пределы папки — отказ", resp["ok"] is False, resp)
        check("requirements.txt не тронут", open(traversal_target, "rb").read() == before_target)

        _, state404 = run_job(api, f"{base}/film/404/")
        check("error_kind для 404", state404.get("error_kind") == "not_found", state404.get("error_kind"))

        saved_min = downloader.MIN_FREE_DISK_BYTES
        downloader.MIN_FREE_DISK_BYTES = 10 ** 18
        _, state_disk = run_job(api, f"{base}/small.mp4")
        downloader.MIN_FREE_DISK_BYTES = saved_min
        check("error_kind для нехватки места", state_disk.get("error_kind") == "disk", state_disk.get("error_kind"))
    finally:
        storage.history_forget(done_name)
        storage.history_forget("zzqa_victim.mp4")

    print("\n=== версия и обновления ===")
    check("версия — три числа", len(APP_VERSION.split(".")) == 3
          and all(part.isdigit() for part in APP_VERSION.split(".")), APP_VERSION)
    check("0.10.0 новее 0.9.0 (сравнение числами, а не строками)",
          updater.is_newer("0.10.0", "0.9.0"))
    check("тег с буквой v разбирается", updater.parse_version("v0.10.0") == (0, 10, 0))
    check("та же версия не считается новой", not updater.is_newer(APP_VERSION, APP_VERSION))
    check("пустой тег не считается новой версией", not updater.is_newer("", APP_VERSION))

    check("нет релизов (404) — это не ошибка",
          updater.check_now(f"{base}/releases/none")["state"] == "no_releases")
    check("та же версия — up_to_date",
          updater.check_now(f"{base}/releases/same")["state"] == "up_to_date")
    check("GitHub не ответил — состояние unavailable с человеческим текстом",
          updater.check_now("http://127.0.0.1:9/latest")["state"] == "unavailable"
          and bool(updater.get_state()["error"]) and bool(updater.get_state()["error_detail"]))

    state = updater.check_now(f"{base}/releases/newer")
    check("новая версия найдена", state["state"] == "available", state["latest_version"])
    check("из файлов релиза выбран установщик",
          state["asset_name"] == "video-downloader-99.0.0-setup.exe", state["asset_name"])

    update_state = call(api.get_update_state)
    check("get_update_state отдаёт состояние", update_state["state"] == "available", update_state["state"])
    check("get_update_state сообщает текущую версию", update_state["current_version"] == APP_VERSION)

    print("\n=== установка обновления ===")
    launched = []
    saved_popen = subprocess.Popen

    class FakePopen:
        """Настоящий установщик в тестах запускать нельзя."""
        def __init__(self, args, *a, **kw):
            launched.append(args)

    subprocess.Popen = FakePopen
    closed = []
    install_api = quiet_api(close_window=lambda: closed.append(True))
    try:
        check("установка началась", call(install_api.install_update)["ok"] is True)
        for _ in range(300):
            if updater.get_state()["state"] in ("installing", "install_error"):
                break
            time.sleep(0.1)
        final = updater.get_state()
        check("установщик скачан и запущен", final["state"] == "installing", final.get("error_detail"))
        check("файл установщика лежит во временной папке",
              bool(launched) and os.path.isfile(launched[0][0])
              and os.path.getsize(launched[0][0]) == len(INSTALLER))
        check("окно закрывается после запуска установщика", bool(closed))
        check("повторная установка не запускается",
              call(install_api.install_update)["ok"] is False)

        print("\n=== показать файл в папке ===")
        launched.clear()
        check("несуществующий файл — отказ",
              call(api.reveal_file, "nosuchfile.mp4")["ok"] is False)
        probe = os.path.join(storage.current_download_dir(), "zzqa_reveal_probe.mp4")
        with open(probe, "wb") as fh:
            fh.write(b"x")
        created_files.append(probe)
        check("существующий файл — успех",
              call(api.reveal_file, "zzqa_reveal_probe.mp4")["ok"] is True)
        check("проводник вызван с /select и путём к файлу",
              bool(launched) and launched[0][0] == "explorer"
              and launched[0][1] == f"/select,{probe}", launched)
    finally:
        for args in launched:
            path = args[0] if isinstance(args, list) else args
            if isinstance(path, str) and os.path.isfile(path) and path.endswith(".exe"):
                os.remove(path)
        subprocess.Popen = saved_popen

    print("\n=== пути из исходников и в собранном виде ===")
    check("корень проекта — не папка пакета",
          os.path.normcase(storage.PROJECT_DIR) == os.path.normcase(ROOT), storage.PROJECT_DIR)
    check("из исходников качаем в downloads в корне проекта",
          os.path.normcase(storage.default_download_dir()) == os.path.normcase(os.path.join(ROOT, "downloads")),
          storage.default_download_dir())
    check("settings.json и history.json — в корне проекта",
          os.path.normcase(storage.SETTINGS_PATH) == os.path.normcase(os.path.join(ROOT, "settings.json"))
          and os.path.normcase(storage.HISTORY_PATH) == os.path.normcase(os.path.join(ROOT, "history.json")),
          (storage.SETTINGS_PATH, storage.HISTORY_PATH))
    storage.FROZEN = True
    frozen_dir = storage.default_download_dir()
    storage.FROZEN = False
    check("в собранном виде качаем в профиль пользователя, а не в папку программы",
          frozen_dir.startswith(os.path.expanduser("~"))
          and not frozen_dir.startswith(storage.RESOURCE_DIR), frozen_dir)

    print("\n=== адрес страницы не поднимает сервер pywebview ===")
    from webview.util import is_local_url
    ui_url = storage.ui_index_url()
    check("адрес страницы — file:///", ui_url.startswith("file:///"), ui_url)
    check("pywebview не считает адрес локальным (иначе поднимет свой сервер)",
          is_local_url(ui_url) is False, ui_url)

    print("\n=== страница: файлы ui ===")
    ui_files = {name: os.path.join(ROOT, "ui", name) for name in ("index.html", "styles.css", "app.js")}
    check("есть index.html, styles.css и app.js", all(os.path.isfile(path) for path in ui_files.values()))
    check("окно найдёт страницу в ресурсах", os.path.isfile(os.path.join(storage.UI_DIR, "index.html")))
    ui_text = {}
    for name, path in ui_files.items():
        try:
            with open(path, encoding="utf-8") as fh:
                ui_text[name] = fh.read()
        except OSError:
            ui_text[name] = ""
    page = ui_text["index.html"]
    required_ids = ("screen-download", "screen-history", "screen-settings", "dropZone", "progressFill",
                    "updateBanner", "ffmpegBanner", "quality", "qualityPills", "historyList",
                    "historyEmpty", "dirPath", "browseBtn", "autoUpdateToggle", "settingsFoot")
    missing_ids = [name for name in required_ids if f'id="{name}"' not in page]
    check("в разметке все элементы, на которые опирается скрипт", not missing_ids, missing_ids)
    check("есть пункты навигации", 'data-screen="history"' in page and 'data-screen="settings"' in page)
    check("есть favicon", 'rel="icon"' in page)
    check("разметка подключает styles.css и app.js", 'href="styles.css"' in page and 'src="app.js"' in page)
    check("в разметке не осталось Jinja", "{{" not in page and "{%" not in page)
    script = ui_text["app.js"]
    check("скрипт не ходит на сервер", "fetch(" not in script and "/api/" not in script)
    check("в скрипте нет браузерного режима", "desktopMode" not in script)
    called = set(re.findall(r"call\(\s*'([a-z_]+)'", script))
    check("страница вызывает ровно методы Api", called == EXPECTED_API, sorted(called ^ EXPECTED_API))
    check("в стилях нет браузерной раскладки", "data-desktop" not in ui_text["styles.css"])

    print("\n=== точки входа ===")
    leftovers = [name for name in ("app.py", "desktop.py", "app_version.py", "updater.py",
                                   "start-desktop.bat", "templates")
                 if os.path.exists(os.path.join(ROOT, name))]
    check("старых точек входа и шаблона нет", not leftovers, leftovers)
    with open(os.path.join(ROOT, "start.bat"), encoding="utf-8") as fh:
        start_bat = fh.read()
    check("start.bat открывает окно пакета", "-m video_downloader" in start_bat)
    with open(os.path.join(ROOT, "video_downloader", "__main__.py"), encoding="utf-8") as fh:
        main_source = fh.read()
    check("окно открывается адресом file:/// без сервера pywebview",
          "http_server=False" in main_source and "storage.ui_index_url()" in main_source
          and "http_server=True" not in main_source)

    print("\n=== bootstrap: начальное состояние окна ===")
    boot = call(api.bootstrap)
    check("bootstrap отвечает", boot["ok"] is True, boot)
    check("в bootstrap версия", boot.get("version") == APP_VERSION, boot.get("version"))
    check("в bootstrap варианты качества из QUALITY_OPTIONS",
          boot.get("quality_options") == [{"height": h, "label": l} for h, l in storage.QUALITY_OPTIONS])
    check("bootstrap: наличие ffmpeg соответствует реальности",
          boot.get("ffmpeg_available") == downloader.ffmpeg_available())
    check("bootstrap: папка загрузок совпадает с текущей",
          os.path.normcase(boot.get("download_dir") or "") == os.path.normcase(storage.current_download_dir()))
    check("bootstrap: лимита на файл нет", boot.get("max_filesize") is None, boot.get("max_filesize"))

    saved_settings = storage.SETTINGS_PATH
    storage.SETTINGS_PATH = os.path.join(storage.current_download_dir(), "zzqa_settings3.json")
    created_files.append(storage.SETTINGS_PATH)
    try:
        call(api.set_quality, 1080)
        check("bootstrap отдаёт сохранённое качество", call(api.bootstrap)["selected_height"] == 1080)
        storage.write_settings(auto_update=False)
        check("bootstrap отдаёт выключенное автообновление", call(api.bootstrap)["auto_update"] is False)
    finally:
        storage.SETTINGS_PATH = saved_settings

    print("\n=== проверка обновлений не подвешивает старт ===")
    started = time.time()
    updater.start_check_async("http://10.255.255.1/latest")  # адрес, который молчит
    check("start_check_async возвращает управление сразу", time.time() - started < 0.5,
          f"{time.time() - started:.2f} c")

    print("\n=== качество: список и умолчание ===")
    check("по умолчанию 720p", storage.TARGET_HEIGHT == 720, storage.TARGET_HEIGHT)
    check("в списке ровно 1080/720/480", storage.ALLOWED_HEIGHTS == (1080, 720, 480), storage.ALLOWED_HEIGHTS)
    check("у каждого варианта есть подпись с весом",
          all(isinstance(label, str) and "МБ" in label for _, label in storage.QUALITY_OPTIONS))
    check("значение по умолчанию есть в списке", storage.TARGET_HEIGHT in storage.ALLOWED_HEIGHTS)
    check("высота доезжает до сортировки", downloader.build_format_sort(480)[0] == "res:480",
          downloader.build_format_sort(480))
    check("без аргумента берётся умолчание",
          downloader.build_format_sort()[0] == f"res:{storage.TARGET_HEIGHT}")
    check("ограничение по res на всех значениях, не по height",
          all(downloader.build_format_sort(h)[0].startswith("res:")
              and "height" not in str(downloader.build_format_sort(h))
              for h in storage.ALLOWED_HEIGHTS))
    check("кодек остаётся H.264/AAC при любом качестве",
          all(downloader.build_format_sort(h)[1:] == ["vcodec:h264", "acodec:aac"]
              for h in storage.ALLOWED_HEIGHTS))

    print("\n=== качество: мусор откатывается к умолчанию ===")
    for bad in (2160, "4k", None, "", -1, 0, 1081):
        check(f"{bad!r} -> {storage.TARGET_HEIGHT}", storage.normalize_height(bad) == storage.TARGET_HEIGHT,
              storage.normalize_height(bad))
    check("строка с числом из списка принимается", storage.normalize_height("1080") == 1080)

    print("\n=== качество доезжает до ydl_opts ===")
    check("в настройках yt-dlp стоит выбранная высота",
          downloader.build_ydl_opts("out.%(ext)s", 480, lambda d: None)["format_sort"][0] == "res:480")
    check("заголовки чистые: только User-Agent",
          list(downloader.build_ydl_opts("out.%(ext)s", 720, lambda d: None)["headers"]) == ["User-Agent"],
          downloader.build_ydl_opts("out.%(ext)s", 720, lambda d: None)["headers"])
    check("restrictfilenames выключен — иначе кириллица схлопывается в '_'",
          "restrictfilenames" not in downloader.build_ydl_opts("out.%(ext)s", 720, lambda d: None))

    seen = []
    saved_builder = downloader.build_ydl_opts

    def spy(outtmpl, height, hook):
        seen.append(height)
        return saved_builder(outtmpl, height, hook)

    downloader.build_ydl_opts = spy
    try:
        _, state = run_job(api, f"{base}/small.mp4", quality=480)
        check("выбор из вызова дошёл до загрузки", seen == [480], seen)
        check("загрузка с выбранным качеством прошла", state["status"] == "finished", state.get("error"))
        seen.clear()
        run_job(api, f"{base}/small.mp4", quality=2160)
        check("мусорное качество превратилось в умолчание", seen == [storage.TARGET_HEIGHT], seen)
        seen.clear()
        run_job(api, f"{base}/small.mp4")
        check("без параметра берётся умолчание", seen == [storage.TARGET_HEIGHT], seen)
    finally:
        downloader.build_ydl_opts = saved_builder

    print("\n=== качество запоминается между запусками ===")
    saved_settings = storage.SETTINGS_PATH
    storage.SETTINGS_PATH = os.path.join(storage.current_download_dir(), "zzqa_settings.json")
    created_files.append(storage.SETTINGS_PATH)
    try:
        check("файла нет — берётся умолчание", storage.read_saved_height() == storage.TARGET_HEIGHT)
        check("set_quality принимает выбор", call(api.set_quality, 1080)["quality"] == 1080)
        check("выбор дожил до диска (как при следующем запуске)", storage.read_saved_height() == 1080)
        check("окно открывается с сохранённым выбором", call(api.bootstrap)["selected_height"] == 1080)
        check("set_quality не принимает мусор",
              call(api.set_quality, "4k")["quality"] == storage.TARGET_HEIGHT)
        with open(storage.SETTINGS_PATH, "w", encoding="utf-8") as fh:
            fh.write("{это не json")
        check("испорченный файл не роняет приложение", storage.read_saved_height() == storage.TARGET_HEIGHT)
    finally:
        storage.SETTINGS_PATH = saved_settings

    print("\n=== настройки: словарь из трёх ключей ===")
    saved_settings = storage.SETTINGS_PATH
    storage.SETTINGS_PATH = os.path.join(storage.current_download_dir(), "zzqa_settings2.json")
    created_files.append(storage.SETTINGS_PATH)
    try:
        with open(storage.SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump({"target_height": 1080}, fh)
        check("старый формат файла читается", storage.read_settings()["target_height"] == 1080)
        check("недостающие ключи получают умолчания",
              storage.read_settings()["auto_update"] is True and storage.read_settings()["download_dir"] is None)

        storage.write_settings(auto_update=False)
        check("частичная запись не теряет соседние ключи",
              storage.read_settings()["target_height"] == 1080 and storage.read_settings()["auto_update"] is False)

        with open(storage.SETTINGS_PATH, "w", encoding="utf-8") as fh:
            fh.write("{это не json")
        broken = storage.read_settings()
        check("испорченный файл — все три ключа умолчания",
              broken == dict(storage.DEFAULT_SETTINGS), broken)

        check("set_auto_update выключает",
              call(api.set_auto_update, False) == {"ok": True, "auto_update": False})
        check("выключенное автообновление — get_update_state отдаёт disabled",
              call(api.get_update_state)["state"] == "disabled")
        update_checks.clear()
        check("set_auto_update включает обратно",
              call(api.set_auto_update, True) == {"ok": True, "auto_update": True})
        check("включение сразу запускает проверку обновлений", update_checks == [True], update_checks)
        check("включённое автообновление — get_update_state не молчит",
              call(api.get_update_state)["state"] != "disabled")
    finally:
        storage.SETTINGS_PATH = saved_settings

    print("\n=== мост Api: что видит страница ===")
    public = {name for name in dir(api) if not name.startswith("_")}
    check("странице видны ровно методы-действия", public == EXPECTED_API, sorted(public ^ EXPECTED_API))
    wired = quiet_api(close_window=lambda: None, pick_folder=lambda: None)
    wired_public = {name for name in dir(wired) if not name.startswith("_")}
    check("колбэки окна не утекают в страницу", wired_public == EXPECTED_API,
          sorted(wired_public ^ EXPECTED_API))
    check("всё видимое — методы", all(inspect.ismethod(getattr(api, name)) for name in EXPECTED_API))

    print("\n=== мост Api: мусор со страницы не роняет ===")
    saved_settings = storage.SETTINGS_PATH
    storage.SETTINGS_PATH = os.path.join(storage.current_download_dir(), "zzqa_settings4.json")
    created_files.append(storage.SETTINGS_PATH)
    try:
        garbage = (None, 123, {}, [], "")
        for name in ("get_progress", "cancel", "reveal_file", "delete_file"):
            outcomes = []
            for value in garbage:
                try:
                    outcomes.append(call(getattr(api, name), value).get("ok"))
                except Exception as exc:
                    outcomes.append(repr(exc))
            check(f"{name}: мусор даёт отказ, а не исключение",
                  outcomes == [False] * len(garbage), outcomes)

        with downloader.jobs_lock:
            jobs_before = len(downloader.jobs)
        outcomes = []
        for args in ((None, "x"), (123, None), ({}, None)):
            try:
                outcomes.append(call(api.start_download, *args).get("ok"))
            except Exception as exc:
                outcomes.append(repr(exc))
        with downloader.jobs_lock:
            jobs_after = len(downloader.jobs)
        check("start_download: мусор даёт отказ", outcomes == [False, False, False], outcomes)
        check("start_download: на мусор задача не заводится", jobs_after == jobs_before,
              (jobs_before, jobs_after))

        resp = call(api.set_quality, {})
        check("set_quality: мусор превращается в умолчание",
              resp.get("ok") is True and resp.get("quality") == storage.TARGET_HEIGHT, resp)

        try:
            resp = call(api.get_history, "лишний аргумент")
        except Exception as exc:
            resp = {"exception": repr(exc)}
        check("лишний аргумент со страницы — отказ, а не исключение",
              resp.get("ok") is False and resp.get("error") == "Внутренняя ошибка приложения.", resp)
    finally:
        storage.SETTINGS_PATH = saved_settings

    print("\n=== Flask ушёл ===")
    sources = package_sources()
    with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as fh:
        requirements = [line.strip() for line in fh if line.strip() and not line.strip().startswith("#")]
    check("все зависимости с точной версией",
          bool(requirements) and all("==" in line for line in requirements), requirements)
    check("Flask, Werkzeug и Jinja2 не в зависимостях",
          not any(line.lower().startswith(("flask", "werkzeug", "jinja2")) for line in requirements),
          requirements)
    check("код пакета не импортирует Flask",
          not re.search(r"^\s*(import|from)\s+(flask|werkzeug|jinja2)\b", sources, re.MULTILINE | re.IGNORECASE))

    print("\n=== кода для fbfind не осталось ===")
    check("извлекатель fbfind удалён", not hasattr(downloader, "extract_video_url_from_fbfind"))
    check("извлекатель через playwright удалён", not hasattr(downloader, "extract_video_with_playwright"))
    check("в коде пакета нет упоминаний fbfind", "fbfind" not in sources.lower())

    print("\n=== устойчивость ===")
    try:
        downloader.finish_job("no-such-job", status="finished")
        check("finish_job не падает на удалённой задаче", True)
    except Exception as exc:
        check("finish_job не падает на удалённой задаче", False, repr(exc))

    server.shutdown()

    for path in created_files:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError as exc:
            print(f"  (не удалось убрать за собой {os.path.basename(path)}: {exc})")

    passed = sum(results)
    print(f"\n==== {passed}/{len(results)} проверок пройдено ====")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
