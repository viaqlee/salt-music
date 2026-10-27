; Salt Music for Windows: Inno Setup 6 script.
; Built by installer\build.ps1, which passes /DAppVersion=... and packs dist\SaltMusic first.
; Classic wizard, per-user install (no administrator rights needed).

#ifndef AppVersion
  #define AppVersion "0.3.2"
#endif
#define AppName "Salt Music"
#define AppExe "SaltMusic.exe"
#define AppUserModelID "SaltMusic.SaltMusic"
#ifdef Bundled
  #define BundledFlag "True"
#else
  #define BundledFlag "False"
#endif

[Setup]
AppId={{6C1E5B7A-3F2D-4C8E-9B0A-5A17D3E2C9F4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Salt Music
DefaultDirName={localappdata}\Programs\SaltMusic
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=SaltMusic-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
WizardSmallImageFile=wizard-small-55.bmp,wizard-small-110.bmp
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=classic
WindowVisible=yes
WindowShowCaption=yes
WindowResizable=no
BackColor=$8A3A0E
BackColor2=$3A1404
BackColorDirection=toptobottom
CloseApplications=yes
RestartApplications=no
SetupMutex=SaltMusicSetup

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ru.DesktopIcon=Создать значок на рабочем столе
en.DesktopIcon=Create a desktop shortcut
ru.ToolsGroup=Недостающие программы (через winget):
en.ToolsGroup=Missing tools (via winget):
ru.ToolFFmpeg=FFmpeg — конвертация звука (обязательно)
en.ToolFFmpeg=FFmpeg — audio conversion (required)
ru.ToolDeno=Deno — нужен YouTube для расшифровки ссылок
en.ToolDeno=Deno — YouTube needs it to decode links
ru.ToolAdb=Android Platform Tools (adb) — отправка на телефон
en.ToolAdb=Android Platform Tools (adb) — sending to the phone
ru.ToolMpv=mpv — встроенный плеер (Windows спросит права администратора)
en.ToolMpv=mpv — built-in player (Windows will ask for administrator rights)
ru.Installing=Установка %1…
en.Installing=Installing %1…
ru.NoWinget=winget не найден: недостающие программы можно установить позже, подсказки есть в настройках приложения.
en.NoWinget=winget was not found: install the missing tools later, the app's settings show how.
ru.ToolsFailed=Не удалось установить: %1.%n%nПовторите позже через winget (подсказки есть в настройках Salt Music → «Прочее» → «Программы») или укажите там путь к программе. Подробности в журнале установки.
en.ToolsFailed=Could not install: %1.%n%nTry again later with winget (Salt Music settings → Other → Programs show how) or point to the program there. The setup log has details.
ru.RemoveData=Удалить также настройки, историю и журналы Salt Music?%n%nСкачанная музыка не удаляется.
en.RemoveData=Also delete Salt Music settings, history and logs?%n%nDownloaded music is not deleted.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; Flags: unchecked
Name: "tools"; Description: "{cm:ToolsGroup}"; Check: NeedsAnyTool
Name: "tools\ffmpeg"; Description: "{cm:ToolFFmpeg}"; Check: NeedsTool('ffmpeg')
Name: "tools\deno"; Description: "{cm:ToolDeno}"; Check: NeedsTool('deno')
Name: "tools\adb"; Description: "{cm:ToolAdb}"; Check: NeedsTool('adb')
Name: "tools\mpv"; Description: "{cm:ToolMpv}"; Check: NeedsTool('mpv')

[Files]
Source: "..\dist\SaltMusic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; an update started from the app itself runs silently with /RELAUNCH=1
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: RelaunchAfterUpdate

[UninstallDelete]
; versions of yt-dlp downloaded by the app live next to the user data, see [Code]
Type: filesandordirs; Name: "{app}\bin"

[Code]
function RegistryPath(Root: Integer; Exe: String): String;
begin
  { App Paths: where installers like the one of mpv register their exe }
  if not RegQueryStringValue(Root, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\' + Exe, '', Result) then
    Result := '';
  if (Result = '') and
     RegQueryStringValue(Root, 'SOFTWARE\Classes\Applications\' + Exe + '\shell\open\command', '', Result) then
  begin
    if Copy(Result, 1, 1) = '"' then
    begin
      Delete(Result, 1, 1);
      Result := Copy(Result, 1, Pos('"', Result) - 1);
    end;
  end;
end;

function ToolPresent(Name: String): Boolean;
var
  Local, Exe, Reg: String;
begin
  { roughly what the app itself checks, see salt_music/tools.py }
  Local := ExpandConstant('{localappdata}');
  Exe := Name + '.exe';
  Result :=
    FileExists(Local + '\Microsoft\WinGet\Links\' + Exe) or
    FileExists(ExpandConstant('{commonpf64}') + '\WinGet\Links\' + Exe) or
    FileExists(Local + '\SaltMusic\bin\' + Exe) or
    FileExists(ExpandConstant('{commonpf64}') + '\MPV Player\' + Exe) or
    FileExists(GetEnv('USERPROFILE') + '\scoop\shims\' + Exe) or
    (FileSearch(Exe, GetEnv('PATH')) <> '');
  { what winget just put on PATH is only in the registry, not in our environment yet }
  if not Result and RegQueryStringValue(HKCU, 'Environment', 'Path', Reg) then
    Result := FileSearch(Exe, Reg) <> '';
  if not Result and RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', Reg) then
    Result := FileSearch(Exe, Reg) <> '';
  if not Result then
  begin
    Reg := RegistryPath(HKCU, Exe);
    if Reg = '' then
      Reg := RegistryPath(HKLM, Exe);
    Result := (Reg <> '') and FileExists(Reg);
  end;
end;

function RelaunchAfterUpdate: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

function BundledTool(Name: String): Boolean;
begin
  { build.ps1 -BundleTools puts the tools into the package itself }
  Result := {#BundledFlag};
end;

function NeedsTool(Name: String): Boolean;
begin
  Result := (not BundledTool(Name)) and (not ToolPresent(Name));
end;

function NeedsAnyTool: Boolean;
begin
  Result := NeedsTool('ffmpeg') or NeedsTool('deno') or NeedsTool('adb') or NeedsTool('mpv');
end;

function WingetPath: String;
begin
  Result := ExpandConstant('{localappdata}\Microsoft\WindowsApps\winget.exe');
  if not FileExists(Result) then
    Result := FileSearch('winget.exe', GetEnv('PATH'));
end;

var
  Failed: String;

procedure Winget(Id, Title, Tool: String);
var
  Code: Integer;
  Exe: String;
begin
  Exe := WingetPath;
  if Exe = '' then
    Exit;
  WizardForm.StatusLabel.Caption := FmtMessage(CustomMessage('Installing'), [Title]);
  { fixed package ids only: nothing from the user ends up on this command line.
    No --scope: the zip packages (ffmpeg, deno, adb) go to the user anyway, and
    the mpv package is a machine-wide installer that a user scope would rule out. }
  Exec(Exe, 'install --id ' + Id + ' --exact --source winget --silent --accept-package-agreements --accept-source-agreements --disable-interactivity',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
  Log(Format('winget %s -> %d', [Id, Code]));
  if not ToolPresent(Tool) then
  begin
    if Failed <> '' then
      Failed := Failed + ', ';
    Failed := Failed + Title;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then
    Exit;
  if not WizardIsTaskSelected('tools') then
    Exit;
  if WingetPath = '' then
  begin
    SuppressibleMsgBox(CustomMessage('NoWinget'), mbInformation, MB_OK, IDOK);
    Exit;
  end;
  Failed := '';
  if WizardIsTaskSelected('tools\ffmpeg') then Winget('Gyan.FFmpeg', 'FFmpeg', 'ffmpeg');
  if WizardIsTaskSelected('tools\deno') then Winget('DenoLand.Deno', 'Deno', 'deno');
  if WizardIsTaskSelected('tools\adb') then Winget('Google.PlatformTools', 'adb', 'adb');
  if WizardIsTaskSelected('tools\mpv') then Winget('shinchiro.mpv', 'mpv', 'mpv');
  if Failed <> '' then
    SuppressibleMsgBox(FmtMessage(CustomMessage('ToolsFailed'), [Failed]), mbError, MB_OK, IDOK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  if UninstallSilent then
    Exit;
  if MsgBox(CustomMessage('RemoveData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    DelTree(ExpandConstant('{userappdata}\SaltMusic'), True, True, True);
    DelTree(ExpandConstant('{localappdata}\SaltMusic'), True, True, True);
  end;
end;
