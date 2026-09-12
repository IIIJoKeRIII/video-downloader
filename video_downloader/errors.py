"""Ошибки yt-dlp — человеческим языком."""
import re
from urllib.parse import urlparse

# yt-dlp раскрашивает свои ошибки для консоли; в интерфейсе эти коды
# выглядят как мусор вида "[0;31mERROR:[0m".
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


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
