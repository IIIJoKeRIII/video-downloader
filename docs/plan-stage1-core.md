# План этапа 1: ядро без Flask

Составлено 2026-09-12. Основание — [tz-desktop-app.md](tz-desktop-app.md): разделы 2.1, 2.2, 2.8, 2.9, приложение А и строка этапа 1 в разделе 5. Статус: **выполнен 2026-09-13**, окно проверено пользователем — всё работает, допущения 1–4 подтверждены. Версии экшенов в `ci.yml` — `@v7` (на 2026-09-13 актуальнее указанных в шаге 4).

Код до начала этапа — коммит `40b3d2c` («Video Downloader: состояние перед пересборкой»). Оттуда берутся исходные тексты удаляемых файлов: `git show 40b3d2c:app.py`.

---

## 0. Как пользоваться этим документом

Исполнитель не видел обсуждения. Всё нужное — здесь.

1. Шаги 1–5 — строго по порядку. Каждый: «Задача / Что менять / Проверка / Чего НЕ делать».
2. После каждого шага — `python tests/smoke_test.py` до зелёного. Красный — следующий шаг не начинается.
3. После шага 3 — **остановка и показ пользователю**.
4. Код не совпал с описанием — остановиться и сказать, не подгонять.
5. Имена модулей, методов, ключей и тексты в документе — финальные.
6. **С начала шага 1 до конца шага 3 запуск из исходников не работает.** Пользователь запускает приложение из исходников каждый день — предупредить его перед началом и не растягивать шаги 1–3 на разные сессии.

Перед началом: `python tests/smoke_test.py` зелёный на `40b3d2c`; записать число и суммарный размер файлов в `downloads/` и значение `download_dir` из `settings.json` — после этапа они обязаны совпасть.

---

## 1. Задача

Приложение выглядит и работает как сейчас, но внутри нет Flask, веб-сервера, порта и браузерного режима: страница вызывает Python напрямую через мост pywebview (`js_api`). Код `app.py` разнесён по модулям пакета `video_downloader/`. Версии зависимостей зафиксированы, проверки запускаются на GitHub при каждом push.

Что пользователь заметит:
- запуск — `start.bat` (открывает окно); `start-desktop.bat` исчезает;
- при запуске окно сразу тёмное — сейчас до загрузки страницы мелькает белый фон;
- текст баннера «нет ffmpeg» говорит «в папку bin в корне проекта» вместо «рядом с app.py».

Всё остальное в окне — без изменений. Ссылка «Скачать файл» и ручной ввод пути папки существовали только в браузерном режиме, в окне их и так не было.

---

## 2. Факты, на которые опирается план

Проверено чтением исходников pywebview 6.2.1 (`%APPDATA%\Python\Python313\site-packages\webview`) и кода проекта.

| # | Факт | Где | Следствие |
|---|---|---|---|
| 1 | Адрес страницы без схемы (`E:\…\index.html`, `ui/index.html`) pywebview считает «локальным» и **запускает встроенный HTTP-сервер**. Адрес `file:///…` локальным не считается — сервер не запускается | `util.py:75-84` (`is_local_url`), `__init__.py:272-279` | Страница открывается только адресом `file:///`, собранным через `pathlib.Path(...).as_uri()` |
| 2 | Странице отдаются все публичные методы объекта `js_api`; публичные атрибуты-объекты обходятся рекурсивно, их методы тоже уходят в JS; имена с `_` пропускаются | `util.py:190-206` (`get_functions`) | В `Api` публичными бывают только методы-действия. Окно, колбэки — только в полях с `_`, иначе странице станут доступны, например, `destroy` или `evaluate_js` окна |
| 3 | Каждый вызов из страницы выполняется в **новом потоке**; результат проходит через `json.dumps`; исключение отклоняет промис в JS и пишет traceback в лог | `util.py:247-266, 330-336` (`js_bridge_call`) | Методы `Api` возвращают только JSON-совместимые значения и **не бросают исключений** |
| 4 | Сгенерированная JS-функция передаёт в Python все аргументы вызова (`Array.prototype.slice.call(arguments)`), имена параметров не важны | `js/api.js:62-78` | Декоратор на методах `Api` не ломает передачу аргументов. Аргументы идут позиционно: лишний аргумент из JS даёт `TypeError` |
| 5 | `window.pywebview.api` наполняется после загрузки страницы, затем в `window` приходит событие `pywebviewready` | `util.py:225-238` | Страница вызывает Python только после `pywebviewready` |
| 6 | `create_file_dialog(webview.FileDialog.FOLDER)` возвращает кортеж путей или `None`; `webview.FOLDER_DIALOG` устарел | `platforms/winforms.py:722-728`, `__init__.py:97-99` | `(result or [None])[0]`; константа `webview.FileDialog.FOLDER` |
| 7 | В `templates/index.html` Jinja используется в 8 местах (`desktop_mode`, баннер ffmpeg, опции качества, пилюли, путь папки и `readonly`, кнопка «Обзор», тумблер, подпись с версией), к серверу — 15 вызовов `fetch('/api/…')` | чтение файла | Эти места переносятся на `bootstrap()` и `call()` (шаг 2) |
| 8 | Из исходников `settings.json` и `history.json` лежат в корне проекта; у пользователя `download_dir` указывает на `downloads/` проекта с его видео | `settings.json`, `.gitignore`, `app.py` (`BASE_DIR`) | После переезда кода в пакет эти файлы обязаны искаться там же. Папка пакета — не корень проекта (ловушка 1) |

---

## 3. Устройство после этапа — справочник

### 3.1 Файлы

```
video_downloader/
  __init__.py      одна строка docstring
  __main__.py      точка входа: WebView2, логи, окно, фоновые потоки
  api.py           класс Api — бывшие роуты Flask
  downloader.py    задачи, загрузка, уборка обрывков, выбор формата, ffmpeg
  errors.py        humanize_error
  storage.py       пути, качество, настройки, журнал истории, форматирование
  updater.py       перенесён из корня, логика не меняется
  version.py       перенесён из app_version.py
ui/
  index.html       разметка без Jinja
  styles.css       стили из <style> шаблона
  app.js           скрипт из <script> шаблона, fetch → call()
tests/smoke_test.py          переписан на Api
.github/workflows/ci.yml     новый
start.bat                    открывает окно
```

Удаляются: `app.py`, `app_version.py`, `updater.py` (в корне), `desktop.py`, `templates/`, `start-desktop.bat`.

### 3.2 Что куда переезжает из `app.py`

Переезд **без изменения логики**: тело копируется как есть, меняются только обращения к соседним модулям (`storage.X` вместо `X`) и `print` → `log`.

| Модуль | Имена из `app.py` | Новое |
|---|---|---|
| `storage.py` | `FROZEN`, `DOWNLOAD_DIR_NAME`, `QUALITY_OPTIONS`, `ALLOWED_HEIGHTS`, `TARGET_HEIGHT`, `SETTINGS_PATH`, `HISTORY_PATH`, `HISTORY_LIMIT`, `DEFAULT_SETTINGS`, `human_size`, `human_when`, `display_name`, `normalize_height`, `default_download_dir`, `current_download_dir`, `known_dirs`, `resolve_download_file`, `read_settings`, `write_settings`, `read_saved_height`, `write_saved_height`, `read_auto_update`, `read_history`, `write_history`, `history_add`, `history_forget` | `PROJECT_DIR` (вместо `BASE_DIR`), `RESOURCE_DIR`, `UI_DIR`, `LOG_DIR`, `ui_index_url()` |
| `errors.py` | `ANSI_RE`, `humanize_error` | — |
| `downloader.py` | `TRACKING_PARAMS`, `INCOMPLETE_RE`, `is_incomplete_artifact`, `JOB_TTL_SECONDS`, `CLEANUP_INTERVAL_SECONDS`, `MAX_FILESIZE_BYTES`, `MIN_FREE_DISK_BYTES`, `LOCAL_FFMPEG_DIR`, `ffmpeg_path`, `ffmpeg_available`, `build_format`, `build_format_sort`, `jobs`, `jobs_lock`, `normalize_url`, `extractor_key`, `cleanup_job_files`, `finish_job`, `sweep_once`, `janitor_loop`, `build_ydl_opts`, `download_worker`, `public_job` | `start_janitor()` |
| `api.py` | тела всех функций с `@app.route` | `Api`, `_ok`, `_fail`, `_guarded` |
| `__main__.py` | всё из `desktop.py` | `setup_logging()`, флаг `--debug` |

Уходят без замены: объект `app` (Flask), `create_server`, `index`, `get_file`, блок `if __name__ == "__main__"` в `app.py`, импорты `flask` и `werkzeug`. `shutdown_callback` и `folder_dialog_callback` становятся аргументами `Api`.

### 3.3 Импорты внутри пакета

Только так:

```python
from video_downloader import storage, errors

storage.SETTINGS_PATH
```

Никогда `from video_downloader.storage import SETTINGS_PATH`. Проверки на лету подменяют `storage.SETTINGS_PATH`, `storage.FROZEN`, `downloader.MAX_FILESIZE_BYTES`, `downloader.MIN_FREE_DISK_BYTES`, `downloader.build_ydl_opts`, `subprocess.Popen`; имя, скопированное при импорте, подмену не увидит, и проверка молча проверит не то. Единственное исключение — `from video_downloader.version import APP_VERSION`.

`subprocess` импортируется модулем и вызывается как `subprocess.Popen(...)`.

Направление зависимостей, циклов быть не должно: `storage` и `errors` ни от чего в пакете не зависят; `downloader` → `storage`, `errors`; `updater` → `version`; `api` → `downloader`, `storage`, `updater`, `version`; `__main__` → всё. **`webview` импортирует только `__main__.py`** — проверки и CI импортируют пакет без окна.

### 3.4 Методы Api

Ответ — всегда словарь:
- успех: `{"ok": True, …данные}` — те же ключи, что отдавал роут;
- отказ: `{"ok": False, "error": "<текст по-русски>"}`, плюс `"error_detail"`, если он был.

| Метод | Аргументы | Данные при успехе | Тексты отказа | Было |
|---|---|---|---|---|
| `bootstrap()` | — | `version`, `quality_options` (список `{"height", "label"}`), `selected_height`, `ffmpeg_available`, `download_dir`, `auto_update`, `max_filesize` (строка или `None`) | — | переменные шаблона в `index()` |
| `start_download(url, quality)` | строка, число | `job_id` | «Вставьте ссылку на видео» | `POST /api/download` |
| `get_progress(job_id)` | строка | всё из `public_job()` | «Задача не найдена» | `GET /api/progress/<job_id>` |
| `cancel(job_id)` | строка | — | «Задача не найдена» | `POST /api/cancel/<job_id>` |
| `set_quality(quality)` | число | `quality` | — | `POST /api/quality` |
| `set_auto_update(enabled)` | bool | `auto_update` | — | `POST /api/auto-update` |
| `get_update_state()` | — | всё из `updater.get_state()`; `state` = `"disabled"`, если автообновление выключено | — | `GET /api/update` |
| `install_update()` | — | всё из `updater.get_state()` | «Обновление сейчас недоступно.» | `POST /api/update/install` |
| `reveal_file(filename)` | строка | — | «Файл не найден» / «Не удалось открыть папку с файлом» | `POST /api/open-folder/<filename>` |
| `get_history()` | — | `items` | — | `GET /api/history` |
| `delete_file(filename)` | строка | — | «Файл не найден» / «Не удалось удалить файл — возможно, он открыт в другой программе.» | `POST /api/history/delete/<filename>` |
| `choose_download_dir()` | — | `download_dir` или `cancelled: True` | тексты проверок `/api/download-dir` / «Не удалось открыть диалог выбора папки.» / «Выбор папки недоступен.» | `POST /api/browse-folder` + `POST /api/download-dir` |

`GET /api/file/<filename>` не переносится.

---

## 4. Шаги

---

## Шаг 1. Пакет, Api, проверки

### Задача
Бэкенд переезжает из `app.py`, `app_version.py`, `updater.py` в пакет `video_downloader/`; роуты становятся методами `Api`; `tests/smoke_test.py` проверяет то же самое через `Api`. Flask уходит из зависимостей.

### Что менять

**1.1. `video_downloader/__init__.py`** — одна строка: `"""Video Downloader: окно pywebview вокруг yt-dlp."""`

**1.2. `video_downloader/storage.py`** — имена из таблицы 3.2. Начало модуля:

```python
import datetime
import json
import logging
import os
import pathlib
import re
import sys

log = logging.getLogger(__name__)

FROZEN = getattr(sys, "frozen", False)

# Корень проекта, а не папка пакета: из исходников settings.json,
# history.json и downloads/ лежат в корне, и там уже настройки, журнал
# и скачанные видео пользователя.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Вшитые ресурсы (ui, ffmpeg). В собранном приложении — каталог
# PyInstaller, он только для чтения.
RESOURCE_DIR = getattr(sys, "_MEIPASS", PROJECT_DIR)
UI_DIR = os.path.join(RESOURCE_DIR, "ui")
```

- `SETTINGS_PATH` — как в `app.py`, `BASE_DIR` заменить на `PROJECT_DIR`. `HISTORY_PATH` — как в `app.py`.
- `default_download_dir()` — из исходников `os.path.join(PROJECT_DIR, "downloads")`, остальное как было.
- `write_settings`, `write_history`: `print(f"[настройки] не сохранились: {e}")` → `log.warning("настройки не сохранились: %s", e)`; то же для истории.
- Строку уровня модуля `os.makedirs(default_download_dir(), exist_ok=True)` **не переносить**: папку создаёт `current_download_dir()` при каждом обращении, а импорт не должен писать на диск.

Новое:

```python
LOG_DIR = (os.path.join(PROJECT_DIR, "logs") if not FROZEN else
           os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                        "VideoDownloader", "logs"))


def ui_index_url():
    """Адрес страницы для окна.

    Только file:///: путь без схемы pywebview считает «локальным» и
    поднимает свой HTTP-сервер (webview/util.py, is_local_url), а
    приложение не должно слушать ни одного порта.
    """
    return pathlib.Path(UI_DIR, "index.html").as_uri()
```

**1.3. `video_downloader/errors.py`** — `ANSI_RE` и `humanize_error` без изменений.

**1.4. `video_downloader/downloader.py`** — имена из таблицы 3.2. Правки:
- `LOCAL_FFMPEG_DIR = os.path.join(storage.RESOURCE_DIR, "bin")`;
- обращения к соседям: `storage.TARGET_HEIGHT`, `storage.normalize_height`, `storage.current_download_dir`, `storage.history_add`, `storage.human_size`, `errors.humanize_error`, `errors.ANSI_RE`;
- `log = logging.getLogger(__name__)`; `print` → `log.info` для штатных сообщений («экстрактор: …», «[уборка] записей о задачах …»), `log.warning` для «файла нет после загрузки» и «yt-dlp: …», `log.exception` для «неожиданная ошибка» (он внутри `except`, traceback попадёт в лог). Тексты сообщений — те же;
- строку уровня модуля `threading.Thread(target=janitor_loop, …).start()` заменить функцией:

```python
_janitor_started = False


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
```

**1.5. `video_downloader/version.py`** — `APP_VERSION = "0.1.0"`. Комментарий: единственное место номера версии; читают `Api.bootstrap()`, `updater.py`, `build.bat`.

**1.6. `video_downloader/updater.py`** — файл переносится целиком; единственная правка — `from video_downloader.version import APP_VERSION`.

**1.7. `video_downloader/api.py`**:

```python
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
```

Каждый публичный метод — с декоратором `@_guarded`. Тело — тело соответствующего роута (таблица 3.4) с заменами: `request.get_json(...)` → аргументы метода; `jsonify(данные)` → `_ok(данные)`; `jsonify({"error": …}), код` → `_fail(текст, detail)`; обращения к бывшим глобальным — через `downloader.` и `storage.`.

Проверка типов на входе (новое — страница может прислать что угодно):
- `url` не строка → как пустая ссылка;
- `job_id` не строка → «Задача не найдена» (иначе `jobs.get({})` бросит `TypeError`);
- `filename` не строка → «Файл не найден».

Методы, где тело роута меняется больше, чем заменой:

```python
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
        # Выключенная проверка — не «нет обновлений», а «не спрашивали».
        if not storage.read_auto_update():
            state["state"] = "disabled"
        return _ok(**state)

    @_guarded
    def install_update(self):
        if not updater.start_install(self._close_window):
            return _fail("Обновление сейчас недоступно.")
        return _ok(**updater.get_state())

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
        """Проверки из бывшего роута /api/download-dir — тот же порядок, те же тексты."""
```

Тело `_set_download_dir` — тело `set_download_dir()` из `app.py`: занятость задачами → пустой путь (`path.strip()` пустой или `path` не строка) → не абсолютный → указывает на файл → `makedirs` → проба записи `.vd_write_test` → `storage.write_settings(download_dir=path)` → `_ok(download_dir=path)`.

`start_download` создаёт запись в `downloader.jobs` тем же словарём, что роут `/api/download` (включая `"cancel_event": threading.Event()`), и запускает `threading.Thread(target=downloader.download_worker, …)`.

**1.8. `requirements.txt`** — ровно:

```
yt-dlp==2026.7.4
requests==2.34.2
pywebview==6.2.1
```

Это версии, установленные на машине пользователя 2026-09-12 (`pip list`). Если у исполнителя установлены другие — взять установленные, прогнать проверки, указать в отчёте.

**1.9. Удалить** `app.py`, `app_version.py`, `updater.py` из корня. `templates/` и `desktop.py` пока **не трогать**.

**1.10. `tests/smoke_test.py`** — переписать. Файл остаётся один, заглушка `Stub`, `check()`, `created_files` — как были.

Начало:

```python
# Корень считается от файла проверок, а не берётся из storage: проверка
# «пути из исходников» обязана поймать storage.PROJECT_DIR, указывающий
# на папку пакета.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from video_downloader import downloader, storage, updater  # noqa: E402
from video_downloader.api import Api  # noqa: E402
from video_downloader.version import APP_VERSION  # noqa: E402

EXPECTED_API = {
    "bootstrap", "start_download", "get_progress", "cancel", "set_quality",
    "set_auto_update", "get_update_state", "install_update", "reveal_file",
    "get_history", "delete_file", "choose_download_dir",
}


def call(method, *args):
    """Вызов, как его сделает pywebview: результат обязан пережить json.dumps."""
    result = method(*args)
    json.dumps(result)
    return result
```

Правила замены по всему файлу:

| Было | Стало |
|---|---|
| `client = svc.app.test_client()` | `update_checks = []`; `api = Api(start_update_check=lambda: update_checks.append(True))` |
| `client.post("/api/download", json=body).get_json()["job_id"]` | `call(api.start_download, url, quality)["job_id"]` |
| `client.get(f"/api/progress/{job_id}").get_json()` | `call(api.get_progress, job_id)` |
| `.status_code == 200` | `["ok"] is True` |
| `.status_code` 400 / 404 / 409 | `["ok"] is False` |
| `svc.<имя>` | `storage.` / `downloader.` / `updater.` по таблице 3.2 |
| `svc.BASE_DIR` | `ROOT` |
| `svc.APP_VERSION` | `APP_VERSION` |
| `svc.folder_dialog_callback = f` | `Api(pick_folder=f, start_update_check=…)` |
| `svc.shutdown_callback = f` | `Api(close_window=f, start_update_check=…)` |

Блоки, где меняется смысл:

1. **«уборка: записи убираются, файлы остаются»** — последняя проверка через `/api/file` → `storage.resolve_download_file(имя) == old_file` с названием «файл находится по имени после уборки записи». Проверка «СКАЧАННЫЙ ФАЙЛ ОСТАЛСЯ НА ДИСКЕ» — дословно как была.
2. **«папка загрузок»** — через `Api(pick_folder=lambda: <путь>).choose_download_dir()`:
   - новая папка → `ok`, `current_download_dir()` равен ей; загрузка идёт туда;
   - `"relative\\path"` → отказ; путь на существующий файл → отказ; `"   "` → отказ;
   - диалог вернул `None` → `cancelled is True`, настройка не изменилась;
   - фиктивная задача `status="downloading"` в `downloader.jobs` → отказ;
   - `Api()` без `pick_folder` → отказ; `pick_folder`, бросающий `OSError`, → отказ с `error_detail`;
   - в `finally` — вернуть **сохранённое до блока** значение `storage.read_settings()["download_dir"]` через `storage.write_settings(download_dir=…)` и удалить временную папку.
3. **«старая папка продолжает отдавать файлы»** — `/api/file` → `storage.resolve_download_file(имя) == outside_file`.
4. **«история»** — `/api/history` → `call(api.get_history)["items"]`; удаление → `call(api.delete_file, "zzqa_victim.mp4")`; выход за пределы папки → `call(api.delete_file, "../requirements.txt")["ok"] is False` **и `requirements.txt` байт в байт тот же** (раньше целью был `app.py`, его больше нет).
5. **«установка обновления»** — `Api(close_window=lambda: closed.append(True), …)`; `call(api.install_update)["ok"] is True`; повторная — `False`. `call(api.get_update_state)["state"] == "available"`.
6. **«показать файл в папке»** — `call(api.reveal_file, "nosuchfile.mp4")["ok"] is False`; существующий — `True`; аргументы `Popen` проверяются как были.
7. **«пути в собранном виде»** → переименовать в «пути из исходников и в собранном виде»:
   - `storage.PROJECT_DIR == ROOT`;
   - `storage.default_download_dir() == os.path.join(ROOT, "downloads")`;
   - `storage.SETTINGS_PATH == os.path.join(ROOT, "settings.json")`, `storage.HISTORY_PATH == os.path.join(ROOT, "history.json")`;
   - проверка `FROZEN = True` — как была, через `storage.FROZEN`.
8. **«страница»** → заменить блоком **«bootstrap: начальное состояние окна»**:
   - `ok`; `version == APP_VERSION`; `quality_options == [{"height": h, "label": l} for h, l in storage.QUALITY_OPTIONS]`; `ffmpeg_available == downloader.ffmpeg_available()`; `normcase(download_dir) == normcase(storage.current_download_dir())`;
   - на подменённом `storage.SETTINGS_PATH`: после `call(api.set_quality, 1080)` — `selected_height == 1080`; после `storage.write_settings(auto_update=False)` — `auto_update is False`.
9. **«настройки: словарь из трёх ключей»** — `call(api.set_auto_update, False) == {"ok": True, "auto_update": False}`, затем `get_update_state()["state"] == "disabled"`; включение → `{"ok": True, "auto_update": True}`, **заглушка проверки обновлений вызвана** (новая проверка «включение сразу запускает проверку обновлений»), `state != "disabled"`.
10. **«качество запоминается между запусками»** — `call(api.set_quality, 1080)["quality"] == 1080`; «страница открывается с сохранённым выбором» → `call(api.bootstrap)["selected_height"] == 1080`; `"4k"` → `TARGET_HEIGHT`.
11. **«кода для fbfind не осталось»** — `hasattr` на `downloader`; плюс в текстах `video_downloader/*.py` нет подстроки `fbfind`.
12. **«качество доезжает до ydl_opts»** — шпион подменяет `downloader.build_ydl_opts`.

Новые блоки:

- **«мост Api: что видит страница»**
  - `{n for n in dir(Api()) if not n.startswith("_")} == EXPECTED_API`;
  - то же для `Api(close_window=lambda: None, pick_folder=lambda: None)` — колбэки не утекают в страницу;
  - каждое имя из `EXPECTED_API` — `inspect.ismethod`.
- **«мост Api: мусор со страницы не роняет»** (на подменённом `storage.SETTINGS_PATH`)
  - `get_progress`, `cancel`, `reveal_file`, `delete_file` с `None`, `123`, `{}`, `[]`, `""` → словарь с `ok is False`, без исключения;
  - `start_download(None, "x")`, `start_download(123, None)`, `start_download({}, None)` → `ok is False`, **число записей в `downloader.jobs` не изменилось**;
  - `set_quality({})` → `ok`, `quality == storage.TARGET_HEIGHT`;
  - `api.get_history("лишний аргумент")` → `ok is False`, `error == "Внутренняя ошибка приложения."`.
- **«Flask ушёл»**
  - каждая непустая строка `requirements.txt` содержит `==`;
  - ни одна не начинается с `flask`, `werkzeug`, `jinja2` (без учёта регистра);
  - в текстах `video_downloader/*.py` нет `import flask`, `from flask`, `werkzeug`.
- **«импорт ничего не запускает»** — в начале `main()`, до любых вызовов: нет потока с именем `janitor`; после двух вызовов `downloader.start_janitor()` — ровно один.
- **«адрес страницы не поднимает сервер pywebview»**
  - `storage.ui_index_url().startswith("file:///")`;
  - `from webview.util import is_local_url`; `is_local_url(storage.ui_index_url()) is False`.

### Проверка
- `python -m py_compile video_downloader/__init__.py video_downloader/storage.py video_downloader/errors.py video_downloader/downloader.py video_downloader/version.py video_downloader/updater.py video_downloader/api.py tests/smoke_test.py`
- `python tests/smoke_test.py` — 0 падений.
- **Краснеют ли новые проверки** — по очереди вернуть поломку, убедиться в падении, вернуть правку:
  - а) `PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))` → падают «пути из исходников»;
  - б) в `Api.__init__` добавить `self.window = object()` → падает «что видит страница»;
  - в) убрать `try/except` из `_guarded` → падает «мусор не роняет»;
  - г) `ui_index_url()` возвращает `os.path.join(UI_DIR, "index.html")` → падает «не поднимает сервер».
- Число и размер файлов в `downloads/`, значение `download_dir` в `settings.json` — как до шага. В `history.json` нет записей `zzqa_`.

### Чего НЕ делать
- Не менять логику функций при переносе: ни «заодно поправить», ни переименовать. Только `storage.X` / `downloader.X` / `errors.X` и `print` → `log`.
- Не импортировать `webview` нигде, кроме `__main__.py` (шаг 3).
- Не импортировать константы по имени между модулями (3.3).
- Не заводить публичные поля в `Api` — даже «удобные» вроде `self.window` или `self.version`.
- Не менять `_fail` так, чтобы он принимал `**данные`: у него есть параметр `error`, и словарь с ключом `error` (состояние апдейтера, `public_job`) уронит вызов с `TypeError`.
- Не ходить в интернет из проверок: `start_update_check` — всегда заглушка.
- Не трогать `downloads/`, `settings.json`, `history.json` руками.

---

## Шаг 2. Интерфейс `ui/`

### Задача
Шаблон становится статической страницей: разметка, стили и скрипт отдельными файлами; начальное состояние — из `bootstrap()`; все обращения к Python — через одну функцию `call()`. Вид в окне не меняется.

### Что менять

**2.1. `ui/styles.css`** — содержимое `<style>` из `templates/index.html` (строки 9–449) без изменений, кроме:
- удалить правила `body[data-desktop="false"]` и `body[data-desktop="false"] .window` (строки 47–63) — раскладка «окно внутри страницы браузера»;
- `width: 100vw; height: 100vh;` из `body[data-desktop="true"] .window` перенести в правило `.window`, само правило с `data-desktop` удалить;
- в конец добавить:

```css
/* До ответа bootstrap() нет ни качества, ни папки — не показываем экран
   с пустым выбором, который через мгновение сменится настоящим. */
body.booting .content { visibility: hidden; }
```

**2.2. `ui/index.html`** — разметка из `templates/index.html` (строки 1–7 и 451–565) с правками:
- `<style>…</style>` → `<link rel="stylesheet" href="styles.css">`;
- `<body data-desktop="…">` → `<body class="booting">`;
- баннер ffmpeg — всегда в разметке, скрыт:

```html
        <div class="banner banner-warn" id="ffmpegBanner" hidden>
          ffmpeg не найден — качество ограничено 720p. Положите ffmpeg.exe в папку bin в корне проекта.
        </div>
```

- `<select id="quality"></select>` — пустой;
- `<div class="pills" id="qualityPills"></div>` — пустой;
- `<input type="text" id="dirPath" readonly>` — без `value`;
- `<button id="browseBtn">Обзор</button>` — без `style`;
- `<button type="button" class="toggle" id="autoUpdateToggle" aria-pressed="false">`;
- `<div class="settings-foot" id="settingsFoot"></div>` — пустой;
- перед `</body>`: `<script src="app.js"></script>`.

В файле не должно остаться ни `{{`, ни `{%`.

**2.3. `ui/app.js`** — скрипт из `templates/index.html` (строки 568–1193) с правками.

а) Удалить браузерный режим: константу `desktopMode`; в `showFinished` — ветку `else` со ссылкой «Скачать файл» (остаётся «Показать в папке» без условия); блок `if (!desktopMode) { … }` целиком; функцию `saveDownloadDir`; условие `if (browseBtn.style.display !== 'none')` (обработчик вешается всегда).

б) В начало файла:

```js
// Единственная точка вызова Python. Никогда не бросает: отказ моста
// (исключение в Python, неизвестный метод) приходит обычным ответом
// с ok:false, и каждому месту не нужно ловить его отдельно.
async function call(name, ...args) {
  try {
    const bridge = window.pywebview && window.pywebview.api;
    const fn = bridge && bridge[name];
    if (typeof fn !== 'function') {
      return { ok: false, error: 'Внутренняя ошибка приложения.', error_detail: 'Нет метода ' + name };
    }
    return await fn(...args);
  } catch (e) {
    return { ok: false, error: 'Внутренняя ошибка приложения.', error_detail: (e && e.message) || String(e) };
  }
}
```

в) Замены вызовов:

| Было | Стало |
|---|---|
| `fetch('/api/open-folder/' + encodeURIComponent(filename), …)` (2 места) | `call('reveal_file', filename)` |
| `pollProgress`: `fetch('/api/progress/' + currentJobId)` + `if (!res.ok)` | `const data = await call('get_progress', currentJobId);` + `if (!data.ok)` |
| `startDownload`: `fetch('/api/download', …)` + `if (!res.ok)` | `const data = await call('start_download', url, Number(quality.value));` + `if (!data.ok)` |
| `stopDownload` и «Стоп» в истории: `fetch('/api/cancel/' + id, …)` | `call('cancel', id)` |
| `checkUpdate`: `fetch('/api/update')` | `renderUpdate(await call('get_update_state'))`, `try/catch` убрать |
| кнопка «Обновить»: `fetch('/api/update/install', …)` | `await call('install_update')`, `try/catch` убрать |
| `applyQuality`: `fetch('/api/quality', …)` | `call('set_quality', Number(height))` |
| «Повторить»: `fetch('/api/download', …)` + `if (res.ok)` | `const data = await call('start_download', item.url, item.height);` + `if (data.ok)` |
| «Да» в удалении: `fetch('/api/history/delete/' + …)` + `if (res.ok)` | `const data = await call('delete_file', item.filename);` + `if (data.ok)` |
| `loadHistory`: `fetch('/api/history')` в `try` | `const data = await call('get_history');` + `if (!data.ok) { …тот же блок «Не удалось получить список загрузок»…; return; }` |
| тумблер автообновления: `fetch('/api/auto-update', …)` | `const data = await call('set_auto_update', enabled); if (!data.ok) return;` дальше как было |

г) `catch` с текстом `'Ошибка сети: ' + e.message` в `pollProgress` и `startDownload` удалить: сети больше нет, `call` не бросает, отказ показывает существующий `showError(data.error, data.error_detail)`.

д) Кнопка «Обзор»:

```js
browseBtn.addEventListener('click', async () => {
  const data = await call('choose_download_dir');
  if (!data.ok) {
    dirNote.textContent = data.error || 'Не удалось сменить папку';
    return;
  }
  if (data.cancelled) return;
  dirNote.textContent = '';
  dirPath.value = data.download_dir;
});
```

е) Строки `document.querySelectorAll('.pill').forEach((el) => { el.addEventListener('click', …) })` удалить: при выполнении скрипта пилюль ещё нет, обработчик вешается при создании пилюли в `boot()`.

ж) В блоке «запуск» в конце файла `watchUpdate()` перенести в `boot()` — до готовности моста Python недоступен. `setFormState('idle')` и обработчики `btn`, `stopBtn`, `urlInput` оставить на месте.

з) В конец файла:

```js
/* ---------- старт: состояние из Python ---------- */

const qualityPills = document.getElementById('qualityPills');
let booted = false;

async function boot() {
  if (booted) return;
  booted = true;

  const data = await call('bootstrap');
  document.body.classList.remove('booting');
  if (!data.ok) {
    showError(data.error, data.error_detail);
    return;
  }

  data.quality_options.forEach((opt) => {
    const option = document.createElement('option');
    option.value = String(opt.height);
    option.textContent = opt.label;
    option.selected = opt.height === data.selected_height;
    quality.appendChild(option);

    const pill = document.createElement('button');
    pill.type = 'button';
    pill.className = 'pill' + (opt.height === data.selected_height ? ' active' : '');
    pill.dataset.height = String(opt.height);
    pill.textContent = opt.height + 'p';
    pill.addEventListener('click', () => applyQuality(pill.dataset.height));
    qualityPills.appendChild(pill);
  });

  document.getElementById('ffmpegBanner').hidden = data.ffmpeg_available;
  dirPath.value = data.download_dir;
  autoUpdateToggle.setAttribute('aria-pressed', data.auto_update ? 'true' : 'false');
  document.getElementById('settingsFoot').textContent =
    (data.ffmpeg_available ? 'ffmpeg найден.' : 'ffmpeg не найден.') +
    ' Версия ' + data.version + '.' +
    (data.max_filesize ? ' Лимит на файл — ' + data.max_filesize + '.' : '');

  watchUpdate();
}

// Мост pywebview наполняется после загрузки страницы и сообщает об этом
// событием pywebviewready. Если скрипт выполнился позже — мост уже готов.
if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.bootstrap === 'function') {
  boot();
} else {
  window.addEventListener('pywebviewready', boot);
}
```

**2.4. Удалить** папку `templates/`.

**2.5. Проверки** — новый блок «страница: файлы ui» в `tests/smoke_test.py`:
- существуют `ui/index.html`, `ui/styles.css`, `ui/app.js`; `os.path.isfile(os.path.join(storage.UI_DIR, "index.html"))`;
- в `index.html` есть `id="…"` для: `screen-download`, `screen-history`, `screen-settings`, `dropZone`, `progressFill`, `updateBanner`, `ffmpegBanner`, `quality`, `qualityPills`, `historyList`, `historyEmpty`, `dirPath`, `browseBtn`, `autoUpdateToggle`, `settingsFoot`; есть `data-screen="history"`, `data-screen="settings"`, `rel="icon"`, `href="styles.css"`, `src="app.js"`; нет `{{` и `{%`;
- в `app.js` нет `fetch(`, `/api/`, `desktopMode`;
- **набор имён из `re.findall(r"call\(\s*'([a-z_]+)'", app_js)` равен `EXPECTED_API`** — страница не зовёт несуществующий метод и не забыла ни один;
- в `styles.css` нет `data-desktop`.

### Проверка
- `python tests/smoke_test.py` — 0 падений.
- Краснеет ли: в `app.js` заменить `call('get_history')` на `call('get_histry')` → падает проверка набора имён; вернуть.
- Смотреть глазами — на шаге 3, в окне.

### Чего НЕ делать
- Не менять классы, id, вёрстку и тексты сверх перечисленного.
- Не подключать библиотеки и сборку фронтенда.
- Не хранить состояние в `localStorage`: окно работает в приватном режиме, хранилище при каждом запуске пустое.
- Не обращаться к `window.pywebview.api` в обход `call` (кроме проверки готовности в самом конце файла).
- Не вставлять данные из Python через `innerHTML` — только `textContent` и `createElement`, как было.
- Не открывать `ui/index.html` в обычном браузере и не писать заглушку моста «чтобы посмотреть»: браузерного режима больше нет.

---

## Шаг 3. Окно, логи, запуск

**По завершении — остановка и показ пользователю.**

### Задача
Точка входа `python -m video_downloader`: проверка WebView2, логи в файл, окно со страницей `file:///` и мостом `Api`. Старые точки входа удаляются.

### Что менять

**3.1. `video_downloader/__main__.py`.** Из `desktop.py` без изменений переносятся `WINDOW_TITLE`, `WINDOW_WIDTH`, `WINDOW_HEIGHT`, `WINDOW_MIN_SIZE`, `WEBVIEW2_KEYS`, `message_box`, `webview2_installed` и текст сообщения о WebView2. Новое:

```python
LOG_FILE_BYTES = 1024 * 1024
LOG_FILE_COUNT = 5

log = logging.getLogger("video_downloader")


def setup_logging(debug):
    """Логи в файл по кругу; если есть консоль — ещё и в неё.

    У окна без консоли (pythonw, собранный exe) других следов не остаётся,
    и разбирать проблему пользователя было бы нечем.
    """
    os.makedirs(storage.LOG_DIR, exist_ok=True)
    handlers = [logging.handlers.RotatingFileHandler(
        os.path.join(storage.LOG_DIR, "app.log"),
        maxBytes=LOG_FILE_BYTES, backupCount=LOG_FILE_COUNT, encoding="utf-8",
    )]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    debug = "--debug" in argv
    setup_logging(debug)
    log.info("запуск %s (собрано: %s)", APP_VERSION, storage.FROZEN)

    if not webview2_installed():
        message_box(...)  # текст из desktop.py
        return 1

    downloader.start_janitor()
    # Проверку обновлений не ждём: сеть может молчать, окно откроется в любом случае.
    if storage.read_auto_update():
        updater.start_check_async()

    window = None

    def close_window():
        window.destroy()

    def pick_folder():
        # Кортеж путей или None (webview/platforms/winforms.py).
        return (window.create_file_dialog(webview.FileDialog.FOLDER) or [None])[0]

    api = Api(close_window=close_window, pick_folder=pick_folder)
    window = webview.create_window(
        WINDOW_TITLE,
        storage.ui_index_url(),
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=WINDOW_MIN_SIZE,
        # Цвет фона страницы: иначе до её загрузки окно мелькает белым.
        background_color="#14171A",
    )
    webview.start(gui="edgechromium", debug=debug, http_server=False)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log.exception("приложение не запустилось")
        message_box(f"Приложение не смогло запуститься.\n\n{type(e).__name__}: {e}")
        sys.exit(1)
```

Импорты: `ctypes`, `logging`, `logging.handlers`, `os`, `sys`, `winreg`, `webview`, `from video_downloader import downloader, storage, updater`, `from video_downloader.api import Api`, `from video_downloader.version import APP_VERSION`.

**3.2. Удалить** `desktop.py` и `start-desktop.bat`.

**3.3. `start.bat`** — перезаписать, кодировка UTF-8 без BOM:

```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"

python -c "import yt_dlp, webview, requests" 2>nul
if errorlevel 1 (
    echo Устанавливаю зависимости, подождите...
    python -m pip install -r requirements.txt
)

start "" pythonw -m video_downloader
```

**3.4. `.gitignore`** — добавить строку `logs/`.

**3.5. Сборочные файлы** — минимально, чтобы не ссылались на удалённое:
- `video-downloader.spec`: `Analysis(['video_downloader/__main__.py'], pathex=[SPECPATH], …)`, в `datas` — `('ui', 'ui')` вместо `('templates', 'templates')`, `('bin/ffmpeg.exe', 'bin')` остаётся;
- `build.bat`: строка чтения версии — `python -c "from video_downloader.version import APP_VERSION; print(APP_VERSION)"`.

Сборку не запускать (допущение 5).

**3.6. Проверки** — блок «точки входа» в `tests/smoke_test.py`:
- не существуют `app.py`, `desktop.py`, `app_version.py`, `start-desktop.bat`, `templates/`, `updater.py` в корне;
- в `start.bat` есть `-m video_downloader`;
- в `video_downloader/__main__.py` есть `http_server=False` и `storage.ui_index_url()`, нет `http_server=True`.

### Проверка

1. `python -m py_compile video_downloader/__main__.py`; `python tests/smoke_test.py` — 0 падений.
2. **Ручная проверка в окне** — все пункты; результат каждого — в отчёт:
   1. `start.bat` → окно открывается, фон сразу тёмный.
   2. **Порт:** `Get-Process pythonw | ForEach-Object { Get-NetTCPConnection -OwningProcess $_.Id -State Listen -ErrorAction SilentlyContinue }` → пусто (допущение 1).
   3. «Скачать»: в списке качества три варианта, выбрано сохранённое; баннер ffmpeg соответствует наличию ffmpeg.
   4. Короткий ролик → прогресс → «Готово» → «Показать в папке» открывает проводник с выделенным файлом.
   5. «Стоп» во время загрузки → «Скачивание остановлено».
   6. Заведомо неверная ссылка → красный блок с «Подробностями».
   7. «История»: видны видео пользователя и новая загрузка; «Папка» работает; «×» → «Удалить файл? Да / Отмена» → **«Отмена»** на видео пользователя; «Да» — только на своей тестовой загрузке.
   8. «Настройки»: активная пилюля совпадает с выбором на «Скачать»; смена пилюли меняет список на «Скачать»; «Обзор» открывает системный диалог (допущение 2); «Отмена» в диалоге ничего не меняет; выбор другой папки обновляет путь — затем **вернуть прежнюю папку**.
   9. Тумблер автообновления: выключить → закрыть окно → `start.bat` → тумблер выключен; включить обратно.
   10. Перетащить ссылку из браузера в зону (допущение 3); Ctrl+V вне поля вставляет ссылку.
   11. Подпись внизу настроек: «ffmpeg найден. Версия 0.1.0.»
   12. Пилюль ровно три — `boot()` отработал один раз (допущение 4).
   13. `logs/app.log` появился, в нём строка запуска и строки загрузки.
   14. `python -m video_downloader --debug` → открываются инструменты разработчика, в консоли страницы нет ошибок.
3. После проверки — окно закрыто, процессов `pythonw` не осталось; `downloads/` и `download_dir` в `settings.json` — как до этапа.
4. **Остановка.** Показать пользователю: попросить запустить `start.bat` и пройтись самому. Дальше — только после его «ок».

### Чего НЕ делать
- Не передавать в `create_window` путь без `file:///` и не включать `http_server`.
- Не делать окно frameless, не менять размеры окна.
- Не запускать `build.bat` и не ставить PyInstaller.
- Не удалять видео пользователя, проверяя «×».
- Не оставлять висящие процессы `pythonw`.

---

## Шаг 4. Проверки на GitHub

### Задача
При каждом push и pull request GitHub прогоняет `tests/smoke_test.py` на Windows.

### Что менять

**4.1. `.github/workflows/ci.yml`**:

```yaml
name: Проверки

on:
  push:
  pull_request:

jobs:
  smoke:
    runs-on: windows-latest
    timeout-minutes: 15
    env:
      # Консоль раннера не в UTF-8: без этого print с кириллицей
      # в проверках падает с UnicodeEncodeError.
      PYTHONUTF8: "1"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: python -m pip install -r requirements.txt
      - run: python tests/smoke_test.py
```

### Проверка
- Файл валиден: отступы пробелами, без табов.
- Настоящий прогон — только после push, а push — только по команде пользователя. После push: вкладка Actions репозитория, прогон зелёный. Локально зелёный, на GitHub красный — принести вывод прогона, не угадывать (допущение 6).

### Чего НЕ делать
- Не добавлять сборку, релизы, кеш pip — это этапы 3–4 ТЗ.
- Не пушить без команды пользователя.

---

## Шаг 5. Документация и финальная сверка

### Что менять

**5.1. `CLAUDE.md`**
- Вводный абзац: окно pywebview вокруг yt-dlp, браузерного режима нет; в цитате о пересборке — «этап 1 выполнен».
- «Как запускать»: `start.bat`; `python -m video_downloader --debug`; сборка — «не работает до этапа 3 ТЗ».
- «Состав»: файлы из 3.1; раздел «Роуты» → «Методы Api» (кратко по таблице 3.4); «Ключевые функции» — по модулям.
- «Что где настраивается»: константы с указанием модуля.
- «Грабли»: удалить «Порт 5000», «Кеш шаблонов Jinja», «WebView2 блокирует скачивание»; в пункте про `localStorage` убрать слова про порт; в пункте про перерисовку истории `/api/history` → `get_history`. Добавить подтверждённое на этом этапе: путь без `file:///` поднимает сервер pywebview; публичные поля `Api` уходят в страницу; константы между модулями — только через модуль; `PROJECT_DIR` ≠ папка пакета; мост готов только после `pywebviewready`; итоги допущений 1–4.
- Журнал изменений: запись с датой — что изменилось для пользователя и почему, «было 155 проверок, стало N».

**5.2. `.claude/skills/video-downloader-workflow/SKILL.md`** — исправить только утверждения, ставшие ложными, структуру не перекраивать:
- «Flask + yt-dlp + pywebview» → «pywebview + yt-dlp»; «проект живёт в двух видах» → один вид (из исходников и собранный — всё ещё две среды);
- `app.py`, `templates/index.html`, роуты, `/api/...`, `client.get("/")` → модули пакета, `ui/`, методы `Api`, проверки `bootstrap()` и статические проверки `ui/`;
- «сервер слушает только 127.0.0.1» → «приложение не открывает портов; страница — только `file:///`»;
- «имя файла, пришедшее из запроса» → «пришедшее со страницы»;
- `DOWNLOAD_DIR` → `storage.current_download_dir()`; «`cleanup_job_files()` по префиксу `<job_id>_`» → по снимку папки и `is_incomplete_artifact` (устарело ещё до этапа);
- «открыть страницу в браузере» → «открыть окно через `start.bat`»; раздел про порт 5000 и кеш Jinja удалить;
- «CI нет» → «CI гоняет `smoke_test.py` при push, но перед отчётом проверки запускаются локально».

### Финальная сверка
1. `python -m py_compile` на все файлы `video_downloader/` и `tests/smoke_test.py`.
2. `python tests/smoke_test.py` → код 0, `N/N проверок пройдено`.
3. Блок «уборка: записи убираются, файлы остаются» — зелёный.
4. Поиск по коду (без `docs/`): нет `flask`, `werkzeug`, `jinja`, `/api/`, `desktop_mode`, `templates/`.
5. `git status --short`: изменены или добавлены только файлы из этого плана; ничего из `downloads/`.
6. `downloads/` и `download_dir` в `settings.json` — как до этапа.
7. Отчёт: что сделано; число проверок; результаты ручной проверки по пунктам 1–14; какие допущения подтвердились; что осталось. Предложить текст коммита — коммит только по команде пользователя.

---

## 5. Допущения — проверяются запуском

```
ДОПУЩЕНИЕ 1: страница по file:/// с http_server=False — порт не открывается,
  мост js_api работает.
  По исходникам сервер не запускается (факт 1), но мост на file:// не проверен.
  Проверить: шаг 3, пункты 2–4.
  Если порт есть: остановиться, принести PID, порт и app.log. http_server не трогать.
  Если мост молчит (bootstrap не приходит, кнопки ничего не делают): остановиться.
  Запасной путь — отдавать страницу через html= со встроенными CSS и JS — только
  после согласования.

ДОПУЩЕНИЕ 2: create_file_dialog можно вызвать из потока вызова js_api.
  Сейчас desktop.py вызывает его из потока Flask — тоже не главного, но в журнале
  проекта это не подтверждено.
  Проверить: шаг 3, пункт 8.
  Если окно зависает: остановиться и сообщить, обходной путь не изобретать.

ДОПУЩЕНИЕ 3: перетаскивание текста ссылки работает на странице из file://.
  Проверить: шаг 3, пункт 10.
  Если нет: убрать из дропзоны «или перетащите её сюда», сказать в отчёте.

ДОПУЩЕНИЕ 4: boot() отрабатывает ровно один раз при любом порядке «скрипт /
  pywebviewready».
  Проверить: шаг 3, пункт 12.
  Если пилюль шесть: принести порядок событий из консоли --debug.

ДОПУЩЕНИЕ 5: PyInstaller соберёт рабочий exe из video_downloader/__main__.py
  с pathex=[SPECPATH].
  На этом этапе НЕ проверяется — это этап 3 ТЗ.

ДОПУЩЕНИЕ 6: на раннере windows-latest pywebview ставится из requirements.txt
  (нужны колёса pythonnet под Python 3.13), а actions/checkout@v4 и
  actions/setup-python@v5 — актуальные мажорные версии.
  Проверить: первый прогон после push; версии экшенов — на их страницах GitHub.
  Если есть мажор новее: взять новее, указать в отчёте.
```

---

## 6. Ловушки

1. **Корень проекта — не папка пакета.** `os.path.dirname(os.path.abspath(__file__))` в `storage.py` — это `video_downloader/`. Оставить так — приложение из исходников не увидит `settings.json`, `history.json` и `downloads/` пользователя: сбросится выбранная папка, пропадёт история, внутри пакета появятся пустые копии. Поэтому в проверках корень считается от файла проверок.
2. **Путь без `file:///` молча поднимает сервер** (факт 1). Снаружи ничего не видно — окно работает как обычно.
3. **Публичное поле в `Api` утекает в страницу** (факт 2), вместе со всеми методами объекта.
4. **Импорт констант по имени** — подмена в проверках перестаёт действовать, проверка остаётся зелёной и проверяет не то.
5. **`_fail(**словарь)`** — `TypeError` из-за ключа `error`; `_guarded` превратит его во «Внутреннюю ошибку приложения», и выглядеть это будет как поломка совсем в другом месте.
6. **Пилюли без обработчиков** — старый `querySelectorAll('.pill')` выполняется до `boot()` и ничего не находит (2.3 е).
7. **Вызов до `pywebviewready`** — `call` вернёт «Нет метода …». Если такое видно при старте, какой-то вызов ушёл раньше `boot()`.
8. **Проверки пишут в настоящие `settings.json`, `history.json`, `downloads/`** — из исходников это файлы пользователя. Всё, что меняет настройки, — на подменённом `storage.SETTINGS_PATH` или с возвратом **сохранённого** значения `download_dir`, а не `current_download_dir()`.
9. **Процесс `pythonw` переживает закрытое окно**, если какой-то поток не `daemon`. После ручной проверки — убедиться, что процессов нет.

---

## 7. Замечено попутно (в работы не входит)

- `requirements.txt` фиксирует только прямые зависимости; транзитивные (`certifi`, `pythonnet`, `bottle`, …) плавают. Для воспроизводимой сборки нужен lock-файл — вопрос этапа 3 ТЗ.
- Проверки из исходников работают на настоящих `settings.json`, `history.json` и `downloads/` пользователя. Надёжнее гонять их на временной копии корня — отдельная задача.
- До этого этапа проверка `POST /api/auto-update` запускала настоящий запрос к GitHub из тестов. На этом этапе он заменяется заглушкой (шаг 1) — упомянуть в журнале.
