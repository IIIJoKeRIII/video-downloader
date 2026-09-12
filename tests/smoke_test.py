"""Проверки сервиса. Интернет не нужен: поднимается локальный сайт-заглушка.

Запуск из корня проекта:
    python tests/smoke_test.py

Код возврата 0 — всё зелёное, 1 — есть падения.
Файлы, созданные тестом, удаляются; чужие файлы в downloads/ не трогаются.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as svc  # noqa: E402
import updater  # noqa: E402

PORT = 8765
SMALL = b"\x00" * (200 * 1024)
BIG = b"\x00" * (3 * 1024 * 1024)
INSTALLER = b"MZ" + b"\x00" * (200 * 1024)

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
            body = json.dumps({"tag_name": f"v{svc.APP_VERSION}", "assets": []}).encode()
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


def run_job(client, url, timeout=60, quality=None):
    """Ставит задачу и ждёт конечного статуса."""
    body = {"url": url}
    if quality is not None:
        body["quality"] = quality
    job_id = client.post("/api/download", json=body).get_json()["job_id"]
    state = {}
    for _ in range(timeout * 10):
        state = client.get(f"/api/progress/{job_id}").get_json()
        if state["status"] in ("finished", "error", "cancelled"):
            break
        time.sleep(0.1)
    if state.get("filename"):
        created_files.append(os.path.join(svc.current_download_dir(), state["filename"]))
    return job_id, state


def main():
    server = HTTPServer(("127.0.0.1", PORT), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = svc.app.test_client()
    base = f"http://127.0.0.1:{PORT}"

    print("=== выбор качества ===")
    fmt, srt = svc.build_format(), svc.build_format_sort()
    print(f"  ffmpeg: {svc.ffmpeg_available()} | format: {fmt} | sort: {srt}")
    check("ограничение по res, а не по height",
          any(s.startswith("res:") for s in srt) and not any("height" in s for s in srt), srt)
    check("целевое разрешение из TARGET_HEIGHT", f"res:{svc.TARGET_HEIGHT}" in srt)
    check("H.264 в предпочтениях", "vcodec:h264" in srt)
    check("склейка потоков только при наличии ffmpeg",
          ("+bestaudio" in fmt) == svc.ffmpeg_available(), fmt)

    print("\n=== разбор ссылок ===")
    check("трекинговые параметры срезаются",
          svc.normalize_url("https://a.tld/v/?utm_referrer=www.kinopoisk.ru") == "https://a.tld/v/")
    check("полезные параметры сохраняются",
          svc.normalize_url("https://www.youtube.com/watch?v=abc&t=42s&utm_source=x")
          == "https://www.youtube.com/watch?v=abc&t=42s")
    check("известный сайт получает свой экстрактор",
          svc.extractor_key("https://vk.com/video-1_2") != "Generic")
    check("неизвестный сайт уходит в Generic",
          svc.extractor_key(f"{base}/film/1/") == "Generic")

    print("\n=== размеры в человеческом виде ===")
    for value, want in [(0, "0 Б"), (512, "512 Б"), (1536, "1.5 КБ"), (4 * 1024 ** 3, "4.0 ГБ")]:
        check(f"{value} -> {want}", svc.human_size(value) == want, svc.human_size(value))

    print("\n=== скачивание ===")
    _, state = run_job(client, f"{base}/small.mp4")
    check("задача завершилась успехом", state["status"] == "finished",
          state.get("error") or state.get("error_detail"))
    check("файл появился на диске", bool(state["filename"])
          and os.path.isfile(os.path.join(svc.current_download_dir(), state["filename"])))

    print("\n=== ошибки понятны человеку ===")
    _, state = run_job(client, f"{base}/film/404/")
    check("статус error", state["status"] == "error", state.get("status"))
    check("текст объясняет причину", "404" in (state.get("error") or ""), state.get("error"))
    check("технические детали отдельным полем", bool(state.get("error_detail")))
    check("ANSI-коды вычищены", "\x1b" not in (state.get("error_detail") or ""))

    print("\n=== лимит размера (по умолчанию выключен) ===")
    check("MAX_FILESIZE_BYTES выключен", svc.MAX_FILESIZE_BYTES is None, svc.MAX_FILESIZE_BYTES)
    _, state = run_job(client, f"{base}/big.mp4")
    check("большой файл качается без препятствий", state["status"] == "finished", state.get("error"))

    saved = svc.MAX_FILESIZE_BYTES
    svc.MAX_FILESIZE_BYTES = 1024 * 1024
    # Имя файла больше не содержит id задачи — без удаления предыдущего
    # "big.mp4" yt-dlp увидит его на диске и молча пропустит скачивание,
    # даже не дойдя до проверки лимита в хуке.
    stale_big = os.path.join(svc.current_download_dir(), "big.mp4")
    if os.path.isfile(stale_big):
        os.remove(stale_big)
    job_id, state = run_job(client, f"{base}/big.mp4")
    check("включённый лимит останавливает загрузку", state["status"] == "error", state.get("error"))
    check("в тексте настоящий вес файла", "3.0 МБ" in (state.get("error") or ""), state.get("error"))
    check("обрывок не остался",
          not any(svc.is_incomplete_artifact(n) and "big" in n.lower()
                  for n in os.listdir(svc.current_download_dir())))
    svc.MAX_FILESIZE_BYTES = saved

    print("\n=== запас места на диске ===")
    saved_min = svc.MIN_FREE_DISK_BYTES
    svc.MIN_FREE_DISK_BYTES = 10 ** 18
    _, state = run_job(client, f"{base}/small.mp4")
    check("отказ до начала скачивания",
          state["status"] == "error" and "Мало места" in (state.get("error") or ""),
          state.get("error"))
    svc.MIN_FREE_DISK_BYTES = saved_min

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
        check(f"{name!r} -> {expected}", svc.is_incomplete_artifact(name) == expected)

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
        with svc.jobs_lock:
            # Снимок папки не содержит ни того, ни другого файла — оба
            # появились уже "во время" этой задачи.
            svc.jobs[cleanup_job_id] = {"dir_snapshot": set(), "dir": cleanup_dir}
        svc.cleanup_job_files(cleanup_job_id)
        check("докачанное видео пережило уборку", os.path.isfile(ready_file))
        check("обрывок (.part) удалён", not os.path.isfile(broken_file))
        with svc.jobs_lock:
            svc.jobs.pop(cleanup_job_id, None)

        alien_job_id = "zzqaalienjob"
        alien_file = os.path.join(cleanup_dir, "zzqa_alien.mp4.part")
        with open(alien_file, "wb") as fh:
            fh.write(b"alien-bytes")
        with svc.jobs_lock:
            # На этот раз файл УЖЕ есть в снимке — он был в папке до старта
            # задачи, хотя имя и похоже на обрывок. Трогать нельзя.
            svc.jobs[alien_job_id] = {"dir_snapshot": {"zzqa_alien.mp4.part"}, "dir": cleanup_dir}
        svc.cleanup_job_files(alien_job_id)
        check("файл из снимка не тронут, даже похожий на обрывок", os.path.isfile(alien_file))
        with svc.jobs_lock:
            svc.jobs.pop(alien_job_id, None)

        try:
            svc.cleanup_job_files("нет-такой-задачи-vообще")
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
        with svc.jobs_lock:
            svc.jobs[pl_job_id] = {"dir_snapshot": set(), "dir": cleanup_dir}
        svc.cleanup_job_files(pl_job_id)
        check("первое докачанное видео плейлиста цело", os.path.isfile(pl_done_1))
        check("второе докачанное видео плейлиста цело", os.path.isfile(pl_done_2))
        check("недокачанное третье видео удалено", not os.path.isfile(pl_broken))
        with svc.jobs_lock:
            svc.jobs.pop(pl_job_id, None)
    finally:
        import shutil as _shutil_cleanup
        _shutil_cleanup.rmtree(cleanup_dir, ignore_errors=True)

    print("\n=== юникодные имена файлов ===")
    _, state = run_job(client, f"{base}/Тестовое видео.mp4")
    check("юникодное название доехало до файла",
          state["status"] == "finished" and "Тестовое видео" in (state.get("filename") or ""),
          state.get("filename"))
    check("файл реально на диске", bool(state.get("filename"))
          and os.path.isfile(os.path.join(svc.current_download_dir(), state["filename"])))

    print("\n=== плейлист: поля в public_job ===")
    check("у обычной задачи playlist_index/playlist_count пустые",
          state.get("playlist_index") is None and state.get("playlist_count") is None)

    print("\n=== уборка: записи убираются, файлы остаются ===")
    old_id, live_id = "zzqaoldjob", "zzqalivejob"
    old_file = os.path.join(svc.current_download_dir(), f"{old_id}_movie.mp4")
    live_file = os.path.join(svc.current_download_dir(), f"{live_id}_movie.mp4")
    for path in (old_file, live_file):
        with open(path, "wb") as fh:
            fh.write(b"x")
        created_files.append(path)

    stale = time.time() - svc.JOB_TTL_SECONDS - 60
    with svc.jobs_lock:
        svc.jobs[old_id] = {"status": "finished", "finished_at": stale}
        svc.jobs[live_id] = {"status": "downloading", "finished_at": None}

    removed = svc.sweep_once()
    check("протухшая запись убрана из памяти", old_id in removed)
    check("СКАЧАННЫЙ ФАЙЛ ОСТАЛСЯ НА ДИСКЕ", os.path.isfile(old_file))
    check("незавершённая задача не тронута", live_id in svc.jobs)
    check("её файл цел", os.path.isfile(live_file))
    check("ссылка на файл работает после уборки записи",
          client.get(f"/api/file/{os.path.basename(old_file)}").status_code == 200)

    with svc.jobs_lock:
        svc.jobs.pop(live_id, None)

    print("\n=== папка загрузок ===")
    original_dir = svc.current_download_dir()
    new_dir = os.path.join(original_dir, "zzqa_dir_probe")
    try:
        resp = client.post("/api/download-dir", json={"path": new_dir})
        check("смена папки принимается", resp.status_code == 200, resp.get_json())
        check("current_download_dir теперь новая папка",
              os.path.normcase(svc.current_download_dir()) == os.path.normcase(new_dir))

        _, state = run_job(client, f"{base}/small.mp4")
        check("загрузка идёт в новую папку", state["status"] == "finished"
              and os.path.dirname(os.path.join(new_dir, state["filename"])) == new_dir)

        check("относительный путь отклонён",
              client.post("/api/download-dir", json={"path": "relative\\path"}).status_code == 400)
        check("путь на существующий файл отклонён",
              client.post("/api/download-dir", json={"path": os.path.join(new_dir, state["filename"])}).status_code == 400)
        check("пустой путь отклонён",
              client.post("/api/download-dir", json={"path": ""}).status_code == 400)

        with svc.jobs_lock:
            svc.jobs["zzqabusyjob"] = {"status": "downloading"}
        check("смена папки во время загрузки — 409",
              client.post("/api/download-dir", json={"path": original_dir}).status_code == 409)
        with svc.jobs_lock:
            svc.jobs.pop("zzqabusyjob", None)

        check("без диалог-колбэка — 409", client.post("/api/browse-folder").status_code == 409)
        svc.folder_dialog_callback = lambda: new_dir
        try:
            resp = client.post("/api/browse-folder")
            check("с колбэком возвращает путь",
                  resp.status_code == 200 and resp.get_json()["path"] == new_dir, resp.get_json())
        finally:
            svc.folder_dialog_callback = None
    finally:
        client.post("/api/download-dir", json={"path": original_dir})
        check("папка вернулась к исходной",
              os.path.normcase(svc.current_download_dir()) == os.path.normcase(original_dir))
        import shutil as _shutil
        _shutil.rmtree(new_dir, ignore_errors=True)

    print("\n=== старая папка продолжает отдавать файлы после смены ===")
    # Файл лежит в исходной папке, но известен только через журнал —
    # /api/file обязан найти его и там, а не только в текущей DOWNLOAD_DIR.
    outside_dir = os.path.join(original_dir, "zzqa_outside")
    os.makedirs(outside_dir, exist_ok=True)
    outside_file = os.path.join(outside_dir, "zzqa_outside_movie.mp4")
    with open(outside_file, "wb") as fh:
        fh.write(b"x")
    svc.history_add({
        "filename": os.path.basename(outside_file),
        "dir": outside_dir,
        "title": "outside movie",
        "height": 720,
        "url": "http://example.test/outside",
        "size": 1,
        "finished_at": time.time(),
    })
    try:
        check("файл из прежней папки виден в known_dirs", outside_dir in svc.known_dirs())
        resp = client.get(f"/api/file/{os.path.basename(outside_file)}")
        check("файл из прежней папки отдаётся", resp.status_code == 200, resp.status_code)
        resp.close()
    finally:
        svc.history_forget(os.path.basename(outside_file))
        try:
            os.remove(outside_file)
        except OSError as exc:
            print(f"  (не удалось убрать {outside_file}: {exc})")
        try:
            os.rmdir(outside_dir)
        except OSError:
            pass

    print("\n=== история ===")
    _, state = run_job(client, f"{base}/small.mp4", quality=480)
    done_name = state["filename"]
    check("загрузка успешна", state["status"] == "finished", state.get("error"))
    try:
        items = client.get("/api/history").get_json()["items"]
        entry = next((i for i in items if i.get("filename") == done_name), None)
        check("скачанное появилось в истории", entry is not None, items)
        check("у записи есть title/size_text/when",
              entry and entry.get("title") and entry.get("size_text") and entry.get("when"))
        check("качество из журнала", entry and entry.get("height") == 480, entry)

        check("display_name срезает префикс задачи",
              svc.display_name("0123456789abcdef0123456789abcdef_Кино.mp4") == "Кино.mp4")
        check("display_name не портит обычные имена",
              svc.display_name("Кино.mp4") == "Кино.mp4")

        check("human_when: сегодня", svc.human_when(time.time()) == "сегодня")
        check("human_when: вчера", svc.human_when(time.time() - 86400) == "вчера")

        orphan = os.path.join(svc.current_download_dir(), "zzqa_orphan.mp4")
        with open(orphan, "wb") as fh:
            fh.write(b"x")
        created_files.append(orphan)
        items = client.get("/api/history").get_json()["items"]
        orphan_entry = next((i for i in items if i.get("filename") == "zzqa_orphan.mp4"), None)
        check("файл без записи в журнале виден по имени файла",
              orphan_entry is not None and orphan_entry["title"] == "zzqa_orphan.mp4", orphan_entry)

        active_job_id = "zzqahistjob"
        part_file = os.path.join(svc.current_download_dir(), "zzqa_active_video.mp4.part")
        with open(part_file, "wb") as fh:
            fh.write(b"x")
        created_files.append(part_file)
        with svc.jobs_lock:
            svc.jobs[active_job_id] = {"status": "downloading", "progress": 10, "speed": None,
                                       "current_name": None}
        items = client.get("/api/history").get_json()["items"]
        with svc.jobs_lock:
            svc.jobs.pop(active_job_id, None)
        check("обрывок (.part) скрыт из готовых",
              not any(i.get("filename") == "zzqa_active_video.mp4.part" and i["kind"] == "done" for i in items))
        check("активная строка присутствует",
              any(i["kind"] == "active" and i["job_id"] == active_job_id for i in items))

        victim = os.path.join(svc.current_download_dir(), "zzqa_victim.mp4")
        bystander = os.path.join(svc.current_download_dir(), "zzqa_bystander.mp4")
        with open(victim, "wb") as fh:
            fh.write(b"victim-bytes")
        with open(bystander, "wb") as fh:
            fh.write(b"bystander-bytes")
        created_files.append(bystander)
        bystander_before = open(bystander, "rb").read()

        resp = client.post("/api/history/delete/zzqa_victim.mp4")
        check("удаление успешно", resp.status_code == 200, resp.get_json())
        check("файл удалён", not os.path.isfile(victim))
        check("соседний файл цел и не изменился",
              os.path.isfile(bystander) and open(bystander, "rb").read() == bystander_before)

        check("удаление несуществующего — 404",
              client.post("/api/history/delete/zzqa_no_such_file.mp4").status_code == 404)
        traversal_target = os.path.join(svc.BASE_DIR, "app.py")
        before_app = open(traversal_target, "rb").read()
        resp = client.post("/api/history/delete/../app.py")
        check("выход за пределы папки — 404", resp.status_code == 404, resp.status_code)
        check("app.py не тронут", open(traversal_target, "rb").read() == before_app)

        _, state404 = run_job(client, f"{base}/film/404/")
        check("error_kind для 404", state404.get("error_kind") == "not_found", state404.get("error_kind"))

        saved_min = svc.MIN_FREE_DISK_BYTES
        svc.MIN_FREE_DISK_BYTES = 10 ** 18
        _, state_disk = run_job(client, f"{base}/small.mp4")
        svc.MIN_FREE_DISK_BYTES = saved_min
        check("error_kind для нехватки места", state_disk.get("error_kind") == "disk", state_disk.get("error_kind"))
    finally:
        svc.history_forget(done_name)
        svc.history_forget("zzqa_victim.mp4")

    print("\n=== версия и обновления ===")
    check("версия — три числа", len(svc.APP_VERSION.split(".")) == 3
          and all(part.isdigit() for part in svc.APP_VERSION.split(".")), svc.APP_VERSION)
    check("0.10.0 новее 0.9.0 (сравнение числами, а не строками)",
          updater.is_newer("0.10.0", "0.9.0"))
    check("тег с буквой v разбирается", updater.parse_version("v0.10.0") == (0, 10, 0))
    check("та же версия не считается новой", not updater.is_newer(svc.APP_VERSION, svc.APP_VERSION))
    check("пустой тег не считается новой версией", not updater.is_newer("", svc.APP_VERSION))

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

    api = client.get("/api/update").get_json()
    check("/api/update отдаёт состояние", api["state"] == "available", api["state"])
    check("/api/update сообщает текущую версию", api["current_version"] == svc.APP_VERSION)

    print("\n=== установка обновления ===")
    launched = []
    saved_popen = subprocess.Popen

    class FakePopen:
        """Настоящий установщик в тестах запускать нельзя."""
        def __init__(self, args, *a, **kw):
            launched.append(args)

    subprocess.Popen = FakePopen
    closed = []
    svc.shutdown_callback = lambda: closed.append(True)
    try:
        check("установка началась", client.post("/api/update/install").status_code == 200)
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
              client.post("/api/update/install").status_code == 409)

        print("\n=== показать файл в папке ===")
        launched.clear()
        check("несуществующий файл — 404",
              client.post("/api/open-folder/nosuchfile.mp4").status_code == 404)
        probe = os.path.join(svc.current_download_dir(), "zzqa_reveal_probe.mp4")
        with open(probe, "wb") as fh:
            fh.write(b"x")
        created_files.append(probe)
        check("существующий файл — 200",
              client.post("/api/open-folder/zzqa_reveal_probe.mp4").status_code == 200)
        check("проводник вызван с /select и путём к файлу",
              bool(launched) and launched[0][0] == "explorer"
              and launched[0][1] == f"/select,{probe}", launched)
    finally:
        for args in launched:
            path = args[0] if isinstance(args, list) else args
            if isinstance(path, str) and os.path.isfile(path) and path.endswith(".exe"):
                os.remove(path)
        subprocess.Popen = saved_popen
        svc.shutdown_callback = None

    print("\n=== пути в собранном виде ===")
    check("из исходников качаем в downloads рядом с app.py",
          svc.default_download_dir() == os.path.join(svc.BASE_DIR, "downloads"), svc.default_download_dir())
    check("шаблоны ищутся в ресурсах", os.path.isdir(os.path.join(svc.RESOURCE_DIR, "templates")))
    svc.FROZEN = True
    frozen_dir = svc.default_download_dir()
    svc.FROZEN = False
    check("в собранном виде качаем в профиль пользователя, а не в папку программы",
          frozen_dir.startswith(os.path.expanduser("~"))
          and not frozen_dir.startswith(svc.RESOURCE_DIR), frozen_dir)

    print("\n=== страница ===")
    page = client.get("/").get_data(as_text=True)
    check("страница отдаётся", bool(page))
    check("на странице есть баннер обновления", 'id="updateBanner"' in page)
    check("на странице видно версию", svc.APP_VERSION in page)
    check("есть три экрана", 'id="screen-download"' in page and 'id="screen-history"' in page
          and 'id="screen-settings"' in page)
    check("есть пункты навигации", 'data-screen="history"' in page and 'data-screen="settings"' in page)
    check("есть дропзона и полоса прогресса", 'id="dropZone"' in page and 'id="progressFill"' in page)
    check("баннер ffmpeg соответствует реальности",
          ('id="ffmpegBanner"' in page) == (not svc.ffmpeg_available()))
    check("на странице есть favicon", 'rel="icon"' in page)
    check("на странице есть переключатель автообновления и поле папки",
          'id="autoUpdateToggle"' in page and 'id="dirPath"' in page)
    check("значение поля папки совпадает с текущей папкой загрузок",
          f'value="{svc.current_download_dir()}"' in page)

    saved_settings = svc.SETTINGS_PATH
    svc.SETTINGS_PATH = os.path.join(svc.current_download_dir(), "zzqa_settings3.json")
    created_files.append(svc.SETTINGS_PATH)
    try:
        client.post("/api/quality", json={"quality": 1080})
        page = client.get("/").get_data(as_text=True)
        check("активная пилюля совпадает с выбранным качеством",
              'class="pill active" data-height="1080"' in page)
        check("селект и пилюли согласованы",
              '<option value="1080" selected>' in page)

        svc.write_settings(auto_update=False)
        page = client.get("/").get_data(as_text=True)
        check("тумблер отражает выключенную настройку", 'aria-pressed="false"' in page)
    finally:
        svc.SETTINGS_PATH = saved_settings

    print("\n=== проверка обновлений не подвешивает старт ===")
    started = time.time()
    updater.start_check_async("http://10.255.255.1/latest")  # адрес, который молчит
    check("start_check_async возвращает управление сразу", time.time() - started < 0.5,
          f"{time.time() - started:.2f} c")

    print("\n=== качество: список и умолчание ===")
    check("по умолчанию 720p", svc.TARGET_HEIGHT == 720, svc.TARGET_HEIGHT)
    check("в списке ровно 1080/720/480", svc.ALLOWED_HEIGHTS == (1080, 720, 480), svc.ALLOWED_HEIGHTS)
    check("у каждого варианта есть подпись с весом",
          all(isinstance(label, str) and "МБ" in label for _, label in svc.QUALITY_OPTIONS))
    check("значение по умолчанию есть в списке", svc.TARGET_HEIGHT in svc.ALLOWED_HEIGHTS)
    check("высота доезжает до сортировки", svc.build_format_sort(480)[0] == "res:480",
          svc.build_format_sort(480))
    check("без аргумента берётся умолчание", svc.build_format_sort()[0] == f"res:{svc.TARGET_HEIGHT}")
    check("ограничение по res на всех значениях, не по height",
          all(svc.build_format_sort(h)[0].startswith("res:") and "height" not in str(svc.build_format_sort(h))
              for h in svc.ALLOWED_HEIGHTS))
    check("кодек остаётся H.264/AAC при любом качестве",
          all(svc.build_format_sort(h)[1:] == ["vcodec:h264", "acodec:aac"] for h in svc.ALLOWED_HEIGHTS))

    print("\n=== качество: мусор откатывается к умолчанию ===")
    for bad in (2160, "4k", None, "", -1, 0, 1081):
        check(f"{bad!r} -> {svc.TARGET_HEIGHT}", svc.normalize_height(bad) == svc.TARGET_HEIGHT,
              svc.normalize_height(bad))
    check("строка с числом из списка принимается", svc.normalize_height("1080") == 1080)

    print("\n=== качество доезжает до ydl_opts ===")
    check("в настройках yt-dlp стоит выбранная высота",
          svc.build_ydl_opts("out.%(ext)s", 480, lambda d: None)["format_sort"][0] == "res:480")
    check("заголовки чистые: только User-Agent",
          list(svc.build_ydl_opts("out.%(ext)s", 720, lambda d: None)["headers"]) == ["User-Agent"],
          svc.build_ydl_opts("out.%(ext)s", 720, lambda d: None)["headers"])
    check("restrictfilenames выключен — иначе кириллица схлопывается в '_'",
          "restrictfilenames" not in svc.build_ydl_opts("out.%(ext)s", 720, lambda d: None))

    seen = []
    saved_builder = svc.build_ydl_opts

    def spy(outtmpl, height, hook):
        seen.append(height)
        return saved_builder(outtmpl, height, hook)

    svc.build_ydl_opts = spy
    try:
        _, state = run_job(client, f"{base}/small.mp4", quality=480)
        check("выбор из запроса дошёл до загрузки", seen == [480], seen)
        check("загрузка с выбранным качеством прошла", state["status"] == "finished", state.get("error"))
        seen.clear()
        run_job(client, f"{base}/small.mp4", quality=2160)
        check("мусорное качество превратилось в умолчание", seen == [svc.TARGET_HEIGHT], seen)
        seen.clear()
        run_job(client, f"{base}/small.mp4")
        check("без параметра берётся умолчание", seen == [svc.TARGET_HEIGHT], seen)
    finally:
        svc.build_ydl_opts = saved_builder

    print("\n=== качество запоминается между запусками ===")
    saved_settings = svc.SETTINGS_PATH
    svc.SETTINGS_PATH = os.path.join(svc.current_download_dir(), "zzqa_settings.json")
    created_files.append(svc.SETTINGS_PATH)
    try:
        check("файла нет — берётся умолчание", svc.read_saved_height() == svc.TARGET_HEIGHT)
        check("/api/quality принимает выбор",
              client.post("/api/quality", json={"quality": 1080}).get_json()["quality"] == 1080)
        check("выбор дожил до диска (как при следующем запуске)", svc.read_saved_height() == 1080)
        check("страница открывается с сохранённым выбором",
              '<option value="1080" selected>' in client.get("/").get_data(as_text=True))
        check("/api/quality не принимает мусор",
              client.post("/api/quality", json={"quality": "4k"}).get_json()["quality"] == svc.TARGET_HEIGHT)
        with open(svc.SETTINGS_PATH, "w", encoding="utf-8") as fh:
            fh.write("{это не json")
        check("испорченный файл не роняет приложение", svc.read_saved_height() == svc.TARGET_HEIGHT)
    finally:
        svc.SETTINGS_PATH = saved_settings

    print("\n=== настройки: словарь из трёх ключей ===")
    saved_settings = svc.SETTINGS_PATH
    svc.SETTINGS_PATH = os.path.join(svc.current_download_dir(), "zzqa_settings2.json")
    created_files.append(svc.SETTINGS_PATH)
    try:
        with open(svc.SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump({"target_height": 1080}, fh)
        check("старый формат файла читается", svc.read_settings()["target_height"] == 1080)
        check("недостающие ключи получают умолчания",
              svc.read_settings()["auto_update"] is True and svc.read_settings()["download_dir"] is None)

        svc.write_settings(auto_update=False)
        check("частичная запись не теряет соседние ключи",
              svc.read_settings()["target_height"] == 1080 and svc.read_settings()["auto_update"] is False)

        with open(svc.SETTINGS_PATH, "w", encoding="utf-8") as fh:
            fh.write("{это не json")
        broken = svc.read_settings()
        check("испорченный файл — все три ключа умолчания",
              broken == dict(svc.DEFAULT_SETTINGS), broken)

        check("/api/auto-update выключает", client.post("/api/auto-update", json={"enabled": False}).get_json()
              == {"auto_update": False})
        check("выключенное автообновление — /api/update отдаёт disabled",
              client.get("/api/update").get_json()["state"] == "disabled")
        check("/api/auto-update включает обратно", client.post("/api/auto-update", json={"enabled": True}).get_json()
              == {"auto_update": True})
        check("включённое автообновление — /api/update не молчит",
              client.get("/api/update").get_json()["state"] != "disabled")
    finally:
        svc.SETTINGS_PATH = saved_settings

    print("\n=== кода для fbfind не осталось ===")
    check("извлекатель fbfind удалён", not hasattr(svc, "extract_video_url_from_fbfind"))
    check("извлекатель через playwright удалён", not hasattr(svc, "extract_video_with_playwright"))

    print("\n=== устойчивость ===")
    try:
        svc.finish_job("no-such-job", status="finished")
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
