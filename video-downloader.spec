# -*- mode: python ; coding: utf-8 -*-
"""Сборка десктопного приложения: pyinstaller video-downloader.spec

Режим onedir (папка dist\VideoDownloader), а не onefile: иначе вшитый
ffmpeg на 85 МБ распаковывался бы во временный каталог при каждом запуске.
Установщик просто копирует готовую папку.
"""
import os

ICON = os.path.join(SPECPATH, 'assets', 'app.ico')
if not os.path.isfile(ICON):
    ICON = None

a = Analysis(
    ['video_downloader/__main__.py'],
    pathex=[SPECPATH],
    binaries=[],
    datas=[
        ('ui', 'ui'),
        ('bin/ffmpeg.exe', 'bin'),
    ],
    # Отдельные hiddenimports не нужны: yt-dlp и pywebview везут свои
    # PyInstaller-хуки, экстракторы подтягиваются через _extractors.py.
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Перестраховка: в коде этих пакетов больше нет, но если кто-то случайно
    # их импортирует, в дистрибутив они не попадут — playwright тянет браузер
    # на сотни мегабайт.
    excludes=['playwright', 'tkinter', 'selenium', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VideoDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # это приложение, а не сервис: чёрного окна быть не должно
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='VideoDownloader',
)
