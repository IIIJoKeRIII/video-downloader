@echo off
chcp 65001 >nul
cd /d "%~dp0"

python -c "import yt_dlp, webview, requests" 2>nul
if errorlevel 1 (
    echo Устанавливаю зависимости, подождите...
    python -m pip install -r requirements.txt
)

start "" pythonw -m video_downloader
