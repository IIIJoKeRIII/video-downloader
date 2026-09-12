"""Точка входа: python -m video_downloader [--debug].

Окно pywebview на движке WebView2 показывает ui/index.html и вызывает
Python через мост Api — без веб-сервера и без открытых портов.
"""
import ctypes
import logging
import logging.handlers
import os
import sys
import winreg

import webview

from video_downloader import downloader, storage, updater
from video_downloader.api import Api
from video_downloader.version import APP_VERSION

WINDOW_TITLE = f"Video Downloader {APP_VERSION}"
WINDOW_WIDTH = 660
WINDOW_HEIGHT = 600
WINDOW_MIN_SIZE = (600, 520)

# Цвет фона страницы (--bg-content): иначе до её загрузки окно мелькает белым.
WINDOW_BACKGROUND = "#14171A"

LOG_FILE_BYTES = 1024 * 1024
LOG_FILE_COUNT = 5

# Где Windows отмечает установленный WebView2 Runtime.
WEBVIEW2_KEYS = (
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    (winreg.HKEY_CURRENT_USER,
     r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
)

log = logging.getLogger("video_downloader")


def message_box(text, title="Video Downloader"):
    """Способ что-то сказать, когда окна ещё нет: консоли у приложения нет."""
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)


def webview2_installed():
    """Есть ли WebView2.

    Без него pywebview молча откатывается на движок Internet Explorer,
    где интерфейс просто не работает. Лучше честно сказать об этом.
    """
    for root, path in WEBVIEW2_KEYS:
        try:
            with winreg.OpenKey(root, path) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
                if version and version != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


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
        message_box(
            "Не найден компонент Microsoft Edge WebView2 — без него окно "
            "приложения не откроется.\n\n"
            "Установите Microsoft Edge WebView2 Runtime и запустите приложение снова."
        )
        return 1

    downloader.start_janitor()
    # Проверку обновлений не ждём: сеть может молчать, а окно должно
    # открыться в любом случае.
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
        background_color=WINDOW_BACKGROUND,
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
