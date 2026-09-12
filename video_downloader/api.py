"""Всё, что может вызвать страница: window.pywebview.api.<метод>(...)."""
import functools
import logging
import os
import subprocess
import threading
import time
import uuid

from video_downloader import downloader, storage, updater
from video_downloader.version import APP_VERSION

log = logging.getLogger(__name__)


def _ok(**data):
    return {"ok": True, **data}


def _fail(error, detail=None):
    result = {"ok": False, "error": error}
    if detail:
        result["error_detail"] = detail
    return result


def _guarded(method):
    """Метод Api не имеет права бросить исключение.

    pywebview отдал бы странице traceback вместо ответа (webview/util.py,
    js_bridge_call), а интерфейс ждёт словарь с ok и error.
    """
    @functools.wraps(method)
    def wrapper(self, *args):
        try:
            return method(self, *args)
        except Exception as e:
            log.exception("Api.%s", method.__name__)
            return _fail("Внутренняя ошибка приложения.", f"{type(e).__name__}: {e}")
    return wrapper


class Api:
    """Мост для страницы.

    pywebview отдаёт странице все публичные атрибуты этого объекта, а
    публичные объекты обходит рекурсивно (webview/util.py, get_functions).
    Поэтому публичными здесь бывают только методы-действия; окно, колбэки
    и всё прочее — в полях с подчёркиванием.
    """

    def __init__(self, close_window=None, pick_folder=None, start_update_check=None):
        self._close_window = close_window
        self._pick_folder = pick_folder
        # В проверках подменяется: включение автообновления не должно
        # ходить в настоящий GitHub.
        self._start_update_check = start_update_check or updater.start_check_async

    @_guarded
    def bootstrap(self):
        settings = storage.read_settings()
        return _ok(
            version=APP_VERSION,
            quality_options=[{"height": height, "label": label}
                             for height, label in storage.QUALITY_OPTIONS],
            selected_height=settings["target_height"],
            ffmpeg_available=downloader.ffmpeg_available(),
            download_dir=storage.current_download_dir(),
            auto_update=settings["auto_update"],
            max_filesize=(storage.human_size(downloader.MAX_FILESIZE_BYTES)
                          if downloader.MAX_FILESIZE_BYTES else None),
        )

    @_guarded
    def start_download(self, url=None, quality=None):
        url = url.strip() if isinstance(url, str) else ""
        if not url:
            return _fail("Вставьте ссылку на видео")

        # Качество, которого нет в списке, молча заменяется на значение по
        # умолчанию: вызов не роняем, но и в 4K втихую не уходим.
        height = storage.normalize_height(quality)
        job_id = uuid.uuid4().hex
        with downloader.jobs_lock:
            downloader.jobs[job_id] = {
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

        thread = threading.Thread(target=downloader.download_worker, args=(job_id, url, height),
                                  daemon=True)
        thread.start()
        return _ok(job_id=job_id)

    @_guarded
    def get_progress(self, job_id=None):
        if not isinstance(job_id, str):
            return _fail("Задача не найдена")
        with downloader.jobs_lock:
            job = downloader.jobs.get(job_id)
            if job is None:
                return _fail("Задача не найдена")
            return _ok(**downloader.public_job(job))

    @_guarded
    def cancel(self, job_id=None):
        if not isinstance(job_id, str):
            return _fail("Задача не найдена")
        with downloader.jobs_lock:
            job = downloader.jobs.get(job_id)
            if job is None:
                return _fail("Задача не найдена")
            if job["status"] in ("starting", "downloading"):
                job["status"] = "cancelling"
                job["cancel_event"].set()
        return _ok()

    @_guarded
    def set_quality(self, quality=None):
        """Запоминает выбор качества.

        Отдельный метод, а не сохранение внутри start_download: выбор должен
        пережить перезапуск, даже если после него ничего не качали.
        """
        height = storage.normalize_height(quality)
        storage.write_saved_height(height)
        return _ok(quality=height)

    @_guarded
    def set_auto_update(self, enabled=False):
        enabled = bool(enabled)
        storage.write_settings(auto_update=enabled)
        # Включили — проверка стартует сразу, без перезапуска приложения.
        if enabled:
            self._start_update_check()
        return _ok(auto_update=enabled)

    @_guarded
    def get_update_state(self):
        state = updater.get_state()
        # Выключенная проверка — не «нет обновлений», а «не спрашивали»:
        # интерфейс на это состояние просто молчит.
        if not storage.read_auto_update():
            state["state"] = "disabled"
        return _ok(**state)

    @_guarded
    def install_update(self):
        if not updater.start_install(self._close_window):
            return _fail("Обновление сейчас недоступно.")
        return _ok(**updater.get_state())

    @_guarded
    def reveal_file(self, filename=None):
        """Показывает скачанный файл в проводнике."""
        file_path = storage.resolve_download_file(filename) if isinstance(filename, str) else None
        if file_path is None:
            return _fail("Файл не найден")

        try:
            # Запятая после /select — часть синтаксиса explorer, не опечатка.
            subprocess.Popen(["explorer", f"/select,{file_path}"])
        except OSError as e:
            return _fail("Не удалось открыть папку с файлом", f"{type(e).__name__}: {e}")

        return _ok()

    @_guarded
    def get_history(self):
        with downloader.jobs_lock:
            snapshot = [dict(job, job_id=job_id) for job_id, job in downloader.jobs.items()]

        items = []

        for job in snapshot:
            if job["status"] in ("starting", "downloading", "cancelling"):
                items.append({
                    "kind": "active",
                    "job_id": job["job_id"],
                    "title": (storage.display_name(job.get("current_name"))
                              if job.get("current_name") else "Загрузка…"),
                    "progress": job.get("progress"),
                    "speed": job.get("speed"),
                })
            elif job["status"] == "cancelled":
                name = job.get("current_name")
                items.append({
                    "kind": "cancelled",
                    "job_id": job["job_id"],
                    "title": storage.display_name(name) if name else "Загрузка остановлена",
                    "url": job.get("url"),
                    "height": job.get("height"),
                })

        history_items = storage.read_history()
        by_filename = {item["filename"]: item for item in history_items}

        seen_files = set()
        done = []
        for directory in storage.known_dirs():
            try:
                names = os.listdir(directory)
            except OSError:
                continue
            for name in names:
                if name.startswith("."):
                    continue
                if name.split(".")[-1].lower() == "json":
                    continue
                if downloader.is_incomplete_artifact(name):
                    continue
                path = os.path.join(directory, name)
                if not os.path.isfile(path):
                    continue
                if name in seen_files:
                    continue
                seen_files.add(name)

                record = by_filename.get(name)
                if record:
                    title = record.get("title") or storage.display_name(name)
                    height = record.get("height")
                    url = record.get("url")
                    finished_at = record.get("finished_at") or os.path.getmtime(path)
                else:
                    title = storage.display_name(name)
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
                    "size_text": storage.human_size(size),
                    "finished_at": finished_at,
                    "when": storage.human_when(finished_at),
                    "url": url,
                })

        done.sort(key=lambda item: item["finished_at"], reverse=True)
        items.extend(done)
        return _ok(items=items)

    @_guarded
    def delete_file(self, filename=None):
        """Удаляет скачанный файл по явной команде пользователя.

        Единственное место в проекте, где файл пользователя удаляется намеренно:
        всё остальное (уборщик, TTL) чистит только записи в памяти.
        """
        path = storage.resolve_download_file(filename) if isinstance(filename, str) else None
        if path is None:
            return _fail("Файл не найден")

        try:
            os.remove(path)
        except OSError as e:
            return _fail("Не удалось удалить файл — возможно, он открыт в другой программе.",
                         f"{type(e).__name__}: {e}")

        storage.history_forget(os.path.basename(path))
        return _ok()

    @_guarded
    def choose_download_dir(self):
        if self._pick_folder is None:
            return _fail("Выбор папки недоступен.")
        try:
            path = self._pick_folder()
        except Exception as e:
            return _fail("Не удалось открыть диалог выбора папки.", f"{type(e).__name__}: {e}")
        if not path:
            return _ok(cancelled=True)
        return self._set_download_dir(path)

    def _set_download_dir(self, path):
        """Проверяет папку и сохраняет её: занятость, путь, права на запись — в этом порядке."""
        with downloader.jobs_lock:
            busy = any(job["status"] in ("starting", "downloading", "cancelling")
                       for job in downloader.jobs.values())
        if busy:
            return _fail("Идёт загрузка — смените папку после её окончания.")

        path = path.strip() if isinstance(path, str) else ""
        if not path:
            return _fail("Укажите папку для загрузок.")
        if not os.path.isabs(path):
            return _fail("Нужен полный путь к папке, например D:\\Видео.")
        if os.path.exists(path) and not os.path.isdir(path):
            return _fail("По этому пути лежит файл, а не папка.")

        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            return _fail("Не удалось создать папку — проверьте путь и права.",
                         f"{type(e).__name__}: {e}")

        probe = os.path.join(path, ".vd_write_test")
        try:
            with open(probe, "wb") as fh:
                fh.write(b"x")
            os.remove(probe)
        except OSError:
            return _fail("В эту папку нельзя писать — выберите другую.")

        storage.write_settings(download_dir=path)
        return _ok(download_dir=path)
