"""Десктопное приложение: Flask внутри процесса, окно pywebview снаружи.

Ни браузера, ни адресной строки: pywebview открывает нативное окно на
движке WebView2 и показывает в нём ту же страницу, что и веб-версия.
"""
import ctypes
import sys
import threading
import winreg

import webview

import app as service
import updater
from app_version import APP_VERSION

WINDOW_TITLE = f"Video Downloader {APP_VERSION}"
WINDOW_WIDTH = 660
WINDOW_HEIGHT = 600
WINDOW_MIN_SIZE = (600, 520)

# Где Windows отмечает установленный WebView2 Runtime.
WEBVIEW2_KEYS = (
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    (winreg.HKEY_CURRENT_USER,
     r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
)


def message_box(text, title="Video Downloader"):
    """Единственный способ что-то сказать: консоли у приложения нет."""
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


def main():
    if not webview2_installed():
        message_box(
            "Не найден компонент Microsoft Edge WebView2 — без него окно "
            "приложения не откроется.\n\n"
            "Установите Microsoft Edge WebView2 Runtime и запустите приложение снова."
        )
        return 1

    server = service.create_server()
    threading.Thread(target=server.serve_forever, daemon=True, name="flask").start()

    # Проверку обновлений запускаем после сервера и не ждём её результата:
    # сеть может молчать, а окно должно открыться в любом случае.
    if service.read_auto_update():
        updater.start_check_async()

    window = webview.create_window(
        WINDOW_TITLE,
        f"http://127.0.0.1:{server.server_port}/",
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=WINDOW_MIN_SIZE,
    )
    # Установщик обновления запускается из потока Flask, а закрыть окно
    # умеет только pywebview — отдаём ему ссылку на destroy.
    service.shutdown_callback = window.destroy
    # Диалог просит pywebview, а зовут его из потока Flask — окно у нас одно.
    service.folder_dialog_callback = lambda: (
        (window.create_file_dialog(webview.FOLDER_DIALOG) or [None])[0]
    )

    webview.start(gui="edgechromium")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        message_box(f"Приложение не смогло запуститься.\n\n{type(e).__name__}: {e}")
        sys.exit(1)
