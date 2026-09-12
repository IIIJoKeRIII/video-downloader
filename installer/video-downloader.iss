; Установщик Video Downloader. Собирается из build.bat:
;   ISCC.exe /DAppVersion=0.1.0 installer\video-downloader.iss
; Требуется Inno Setup 6.3 или новее (директива ArchitecturesAllowed=x64compatible).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Video Downloader"
#define AppExe "VideoDownloader.exe"

[Setup]
; AppId менять нельзя: по нему Windows понимает, что это обновление,
; а не вторая программа рядом.
AppId={{A86C092E-8C90-42FB-B62A-AF3F4A364E60}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=IIIJoKeRIII
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Ставим в профиль пользователя: тогда обновление не будет каждый раз
; спрашивать права администратора.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=video-downloader-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Иконка установщика и та, что Windows показывает в «Установке и удалении программ».
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
; Перед обновлением приложение закрывает себя само; force — на случай,
; когда установщик запустили руками при открытом окне.
CloseApplications=force

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"

[Files]
Source: "..\dist\VideoDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Необязательный файл: если его не положили рядом с .iss, установщик просто
; соберётся без него.
Source: "MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy skipifsourcedoesntexist

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function WebView2Installed(): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)
         or RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and not WebView2Installed() then
  begin
    try
      ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
      Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
    except
      MsgBox('Не найден компонент Microsoft Edge WebView2. Установите его с сайта Microsoft, иначе окно приложения не откроется.', mbInformation, MB_OK);
    end;
  end;
end;
