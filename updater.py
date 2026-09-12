"""Проверка обновлений через GitHub Releases и запуск нового установщика.

Проверка идёт в фоновом потоке: сеть может не ответить, а окно приложения
обязано открыться в любом случае. Результат складывается в _state, наружу
его отдаёт app.py через /api/update.
"""
import os
import re
import subprocess
import tempfile
import threading

import requests

from app_version import APP_VERSION

# Откуда берём релизы. Репозиторий публичный, токен не нужен.
GITHUB_OWNER = "IIIJoKeRIII"
GITHUB_REPO = "video-downloader"
UPDATE_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

# Сколько ждём ответ GitHub. Проверка обновлений — не повод тормозить запуск.
UPDATE_CHECK_TIMEOUT_SECONDS = 6
# Скачивание установщика — дело долгое, тут запас больше.
UPDATE_DOWNLOAD_TIMEOUT_SECONDS = 300
# По какому окончанию имени узнаём установщик среди файлов релиза.
UPDATE_ASSET_SUFFIX = "setup.exe"

# Возможные значения state:
#   checking      — проверка ещё идёт
#   up_to_date    — установлена свежая версия
#   available     — есть новее, установщик найден
#   no_releases   — релизов в репозитории нет (404 от GitHub)
#   no_asset      — релиз новее есть, но установщика в нём нет
#   unavailable   — GitHub не ответил
#   downloading   — качаем установщик
#   installing    — установщик запущен
#   install_error — скачать установщик не вышло
_state = {
    "state": "checking",
    "current_version": APP_VERSION,
    "latest_version": None,
    "asset_url": None,
    "asset_name": None,
    "progress": None,
    "error": None,
    "error_detail": None,
}
_lock = threading.Lock()


def parse_version(text):
    """'v0.10.0' -> (0, 10, 0). Буквы и хвосты вроде '-beta' отбрасываем."""
    nums = re.findall(r"\d+", text or "")[:3]
    return tuple(int(n) for n in nums) + (0,) * (3 - len(nums))


def is_newer(remote, local):
    """Сравниваем числами, а не строками: '0.10.0' > '0.9.0' как строки — ложь."""
    return parse_version(remote) > parse_version(local)


def get_state():
    with _lock:
        return dict(_state)


def _set(**fields):
    with _lock:
        _state.update(fields)


def check_now(api_url=None):
    """Синхронная проверка. api_url задаётся только в тестах."""
    try:
        response = requests.get(
            api_url or UPDATE_API_URL,
            timeout=UPDATE_CHECK_TIMEOUT_SECONDS,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": f"video-downloader/{APP_VERSION}"},
        )
    except requests.RequestException as e:
        _set(state="unavailable", error="Не удалось проверить обновления — GitHub не ответил.",
             error_detail=f"{type(e).__name__}: {e}")
        return get_state()

    # 404 — это не поломка: значит, релизов в репозитории пока нет.
    if response.status_code == 404:
        _set(state="no_releases", error=None, error_detail=None)
        return get_state()

    if response.status_code != 200:
        _set(state="unavailable", error="Не удалось проверить обновления — GitHub ответил ошибкой.",
             error_detail=f"HTTP {response.status_code}: {response.text[:200]}")
        return get_state()

    data = response.json()
    tag = data.get("tag_name") or ""
    asset = next((a for a in (data.get("assets") or [])
                  if (a.get("name") or "").lower().endswith(UPDATE_ASSET_SUFFIX)), None)

    if not is_newer(tag, APP_VERSION):
        _set(state="up_to_date", latest_version=tag, error=None, error_detail=None)
    elif asset is None:
        _set(state="no_asset", latest_version=tag, error=None, error_detail=None)
    else:
        _set(state="available", latest_version=tag, error=None, error_detail=None,
             asset_url=asset.get("browser_download_url"), asset_name=asset.get("name"))
    return get_state()


def start_check_async(api_url=None):
    """Запускает проверку в фоне и сразу возвращает управление."""
    threading.Thread(target=check_now, args=(api_url,), daemon=True, name="update-check").start()


def _install_worker(shutdown):
    state = get_state()
    # Установщик кладём во временную папку: рядом со скачанными видео
    # ему делать нечего.
    destination = os.path.join(tempfile.gettempdir(), state["asset_name"])
    try:
        with requests.get(state["asset_url"], stream=True,
                          timeout=UPDATE_DOWNLOAD_TIMEOUT_SECONDS) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            received = 0
            with open(destination, "wb") as fh:
                for chunk in response.iter_content(256 * 1024):
                    fh.write(chunk)
                    received += len(chunk)
                    if total:
                        _set(progress=round(received / total * 100, 1))
        subprocess.Popen([destination])
    except Exception as e:
        _set(state="install_error", error="Не удалось скачать установщик обновления.",
             error_detail=f"{type(e).__name__}: {e}")
        return

    _set(state="installing", progress=100, error=None, error_detail=None)
    # Установщик не сможет заменить файлы, пока приложение открыто.
    if shutdown:
        shutdown()


def start_install(shutdown=None):
    """Возвращает False, если обновлять нечего или установка уже идёт."""
    with _lock:
        if _state["state"] != "available":
            return False
        _state.update(state="downloading", progress=0, error=None, error_detail=None)
    threading.Thread(target=_install_worker, args=(shutdown,), daemon=True,
                     name="update-install").start()
    return True
