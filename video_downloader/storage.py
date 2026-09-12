"""Пути, качество, настройки и журнал загрузок.

Ни от чего в пакете не зависит: остальные модули читают его.
"""
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

# Имя папки для скачанных видео в профиле пользователя.
DOWNLOAD_DIR_NAME = "Video Downloader"

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

# Где запоминается выбор пользователя. Хранилище самой страницы тут не
# годится: окно работает в приватном профиле WebView2, и при каждом
# запуске оно пустое.
SETTINGS_PATH = (os.path.join(PROJECT_DIR, "settings.json") if not FROZEN else
                 os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                              "VideoDownloader", "settings.json"))

# Журнал загрузок лежит рядом с настройками: в собранном виде это
# %LOCALAPPDATA%, из исходников — корень проекта.
HISTORY_PATH = os.path.join(os.path.dirname(SETTINGS_PATH), "history.json")

# Сколько записей журнала храним. Речь только про записи: файлы на диске
# не удаляются, даже когда запись о них выпала из журнала.
HISTORY_LIMIT = 200

DEFAULT_SETTINGS = {
    "target_height": TARGET_HEIGHT,
    "download_dir": None,
    "auto_update": True,
}

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


def human_size(num_bytes):
    """Байты в человекочитаемый вид: 1536 -> '1.5 КБ'."""
    if not num_bytes:
        return "0 Б"
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ", "ПБ"):
        if abs(num_bytes) < 1024 or unit == "ПБ":
            return f"{num_bytes:.0f} {unit}" if unit == "Б" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024


def human_when(timestamp):
    """'сегодня' / 'вчера' / '03.02.2026' — по местной дате."""
    day = datetime.date.fromtimestamp(timestamp)
    today = datetime.date.today()
    if day == today:
        return "сегодня"
    if day == today - datetime.timedelta(days=1):
        return "вчера"
    return day.strftime("%d.%m.%Y")


def display_name(filename):
    """Имя файла без служебного префикса задачи (32 hex и подчёркивание)."""
    if not filename:
        return filename
    stripped = re.sub(r"^[0-9a-f]{32}_", "", filename)
    return stripped or filename


def normalize_height(value):
    """Приводит присланное качество к допустимому.

    Чужое значение (опечатка, открытое со вчера окно, «а давайте 2160»)
    не должно ни ронять вызов, ни втихую качать 4K: берём значение по
    умолчанию.
    """
    try:
        height = int(value)
    except (TypeError, ValueError):
        return TARGET_HEIGHT
    return height if height in ALLOWED_HEIGHTS else TARGET_HEIGHT


def default_download_dir():
    """Куда складывать скачанное.

    В собранном приложении писать рядом с exe нельзя (каталог программы
    перезаписывается при обновлении и может быть закрыт на запись), поэтому
    файлы уходят в профиль пользователя: их видно в проводнике, они
    переживают обновление и удаление программы. Из исходников — папка
    downloads в корне проекта.
    """
    if not FROZEN:
        return os.path.join(PROJECT_DIR, "downloads")
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


def known_dirs():
    """Текущая папка загрузок плюс те, где лежат файлы из журнала.

    После смены папки старые файлы никуда не делись — «показать в папке»
    и удаление обязаны находить их и там.
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

    Имя всегда сводится к basename: без этого ../ в имени со страницы
    уводит за пределы папки загрузок.
    """
    safe_name = os.path.basename(filename)
    for directory in known_dirs():
        candidate = os.path.join(directory, safe_name)
        if os.path.isfile(candidate):
            return candidate
    return None


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
        log.warning("настройки не сохранились: %s", e)


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
        log.warning("история не сохранилась: %s", e)


def history_add(record):
    """Кладёт запись первой, вытесняя прежнюю запись про тот же файл."""
    items = [item for item in read_history() if item.get("filename") != record["filename"]]
    items.insert(0, record)
    write_history(items)


def history_forget(filename):
    """Убирает запись о файле. Файл на диске не трогает."""
    items = [item for item in read_history() if item.get("filename") != filename]
    write_history(items)
