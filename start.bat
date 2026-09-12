@echo off
cd /d "%~dp0"

python -c "import flask, yt_dlp" 2>nul
if errorlevel 1 (
    echo Устанавливаю зависимости, подождите...
    pip install -r requirements.txt
)

start "Video Downloader Server" cmd /k python app.py

timeout /t 2 /nobreak >nul
start http://127.0.0.1:5000
