@echo off
cd /d "%~dp0"

python -c "import flask, yt_dlp, webview" 2>nul
if errorlevel 1 (
    echo Устанавливаю зависимости, подождите...
    pip install -r requirements.txt
)

start "" pythonw desktop.py
