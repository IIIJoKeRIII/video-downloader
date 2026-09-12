@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "bin\ffmpeg.exe" (
    echo [ошибка] Нет bin\ffmpeg.exe — положите его туда, он вшивается в дистрибутив.
    exit /b 1
)

python -m PyInstaller --noconfirm --clean video-downloader.spec
if errorlevel 1 exit /b 1

for /f "usebackq delims=" %%v in (`python -c "import app_version; print(app_version.APP_VERSION)"`) do set APP_VERSION=%%v
echo Версия: %APP_VERSION%

set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo [ошибка] Не найден Inno Setup 6: "%ISCC%"
    exit /b 1
)

"%ISCC%" /DAppVersion=%APP_VERSION% "installer\video-downloader.iss"
if errorlevel 1 exit /b 1

echo Готово: dist\video-downloader-%APP_VERSION%-setup.exe
