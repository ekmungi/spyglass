; Inno Setup 6 script for the one-file, per-user Spyglass installer for Windows.
; Build from the repository root after `npm run build` in frontend, with a pinned uv.exe copied to
; installer\uv.exe:  iscc /DAppVersion=0.41.0 installer\spyglass.iss   (see installer\README.md)

#ifndef AppVersion
  #error Pass the version on the command line: iscc /DAppVersion=0.41.0 installer\spyglass.iss
#endif
#if VER < EncodeVer(6, 3, 0)
  #error Inno Setup 6.3 or newer is needed, for its UTF-8 file functions.
#endif
; A fixed id, so that a newer installer finds the installed version and replaces it in place.
#define AppGuid "47FEF1B5-716C-4F96-8B91-F0DFA8A5C7F5"

[Setup]
AppId={{{#AppGuid}}
AppName=Spyglass
AppVersion={#AppVersion}
AppVerName=Spyglass {#AppVersion}
AppPublisher=ekmungi
AppPublisherURL=https://github.com/ekmungi/spyglass
VersionInfoVersion={#AppVersion}
; Per user: no administrator rights, and everything lands in the user's own folders.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Spyglass
DisableDirPage=auto
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Spyglass-Setup-{#AppVersion}
SetupIconFile=spyglass.ico
UninstallDisplayIcon={app}\installer\spyglass.ico
UninstallDisplayName=Spyglass
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The script stops a running Spyglass itself, and only one that the desktop app started.
CloseApplications=no
RestartApplications=no
SetupLogging=yes
UninstallLogging=yes

[Messages]
FinishedLabel=Setup has finished installing [name]. Open it from the Start menu. While Spyglass runs, its icon sits in the notification area, where Windows may hide it behind the ^ arrow.

[InstallDelete]
; On an upgrade, program folders are replaced whole, so a file a newer version dropped cannot
; linger. Only in the folder of an earlier install, never in a folder the user picked first.
Type: filesandordirs; Name: "{app}\src"; Check: IsEarlierInstallFolder
Type: filesandordirs; Name: "{app}\frontend\dist"; Check: IsEarlierInstallFolder
Type: filesandordirs; Name: "{app}\browser-extension"; Check: IsEarlierInstallFolder
Type: filesandordirs; Name: "{app}\skills"; Check: IsEarlierInstallFolder

[Files]
Source: "..\src\*"; DestDir: "{app}\src"; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs ignoreversion
Source: "..\frontend\dist\*"; DestDir: "{app}\frontend\dist"; Flags: recursesubdirs ignoreversion
Source: "..\browser-extension\*"; DestDir: "{app}\browser-extension"; Excludes: "\tests,\tools,node_modules"; Flags: recursesubdirs ignoreversion
Source: "..\skills\*"; DestDir: "{app}\skills"; Flags: recursesubdirs ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "uv.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "spyglass.ico"; DestDir: "{app}\installer"; Flags: ignoreversion

[UninstallDelete]
; What uv and Python made inside the install folder. The data folder and desktop.json stay.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\frontend"
Type: filesandordirs; Name: "{app}\browser-extension"
Type: filesandordirs; Name: "{app}\skills"
Type: filesandordirs; Name: "{app}\installer"
Type: files; Name: "{app}\install.log"
Type: files; Name: "{userprograms}\Spyglass.lnk"
Type: dirifempty; Name: "{app}"

[Run]
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m spyglass_service.desktop"; WorkingDir: "{app}"; Description: "Open Spyglass now"; Flags: postinstall nowait skipifsilent; Check: SetupSucceeded

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  RunValue = 'Spyglass';
  DefaultPort = 7777;
  { How long one local request may take; a busy service still answers its health check in this. }
  RequestTimeoutMs = 2000;
  { How long a stopped Spyglass gets to free its port and end its processes. }
  StopWaitMs = 15000;
  PollMs = 250;
  { Setup's exit codes when the files are in place but Spyglass is not set up. They stay clear of
    Inno Setup's own codes (1 to 8): 100 plus the folder check's code, and 110 for the rest. }
  ExitOlderData = 103;
  ExitNewerData = 104;
  ExitSetupFailed = 110;

var
  DataDirPage: TInputDirWizardPage;
  VaultPage: TInputQueryWizardPage;
  AutostartPage: TInputOptionWizardPage;
  ConfiguredPort: Integer;
  ExistingDataDir, ExistingVault: String;
  ExistingPort: Integer;
  StopNote: String;
  SetupFailure: String;
  CustomExitCode: Integer;

function SetEnvironmentVariable(Name: String; Value: String): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';
{ The same call with a null value, which removes the variable. }
function ClearEnvironmentVariable(Name: String; Value: Cardinal): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';
function GetTickCount: DWORD;
  external 'GetTickCount@kernel32.dll stdcall';

{ ---- Paths and the install log ---- }

function InstallLogPath: String;
begin
  Result := ExpandConstant('{app}\install.log');
end;

function PythonW: String;
begin
  Result := ExpandConstant('{app}\.venv\Scripts\pythonw.exe');
end;

{ Where the desktop app reads its settings: the per-user config folder, under Spyglass. }
function DesktopConfigPath: String;
begin
  Result := ExpandConstant('{localappdata}\Spyglass\desktop.json');
end;

{ Add one line to install.log (UTF-8) and to Setup's own log. }
procedure AppendLog(Text: String);
var
  Lines: TArrayOfString;
begin
  Log(Text);
  SetArrayLength(Lines, 1);
  Lines[0] := Text;
  SaveStringsToUTF8FileWithoutBOM(InstallLogPath, Lines, True);
end;

{ A path as one quoted command-line argument: a trailing backslash would escape the quote. }
function ArgPath(Path: String): String;
begin
  Result := RemoveBackslashUnlessRoot(Path);
  if Copy(Result, Length(Result), 1) = '\' then
    Result := Result + '.';
end;

function IsInside(Path, Folder: String): Boolean;
begin
  Result := Pos(AnsiLowercase(AddBackslash(Folder)), AnsiLowercase(AddBackslash(Path))) = 1;
end;

{ Whether Dir is where this app was installed before, by Windows' own uninstall record. A
  repository clone has the same folders, so the files in it cannot tell. }
function IsEarlierInstall(Dir: String): Boolean;
var
  Location: String;
begin
  Result := RegQueryStringValue(HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + '{' + '{#AppGuid}' + '}_is1',
      'InstallLocation', Location)
    and (AnsiLowercase(RemoveBackslash(Location)) = AnsiLowercase(RemoveBackslash(Dir)));
end;

function IsEarlierInstallFolder: Boolean;
begin
  Result := IsEarlierInstall(ExpandConstant('{app}'));
end;

function ForeignFolderMessage(Dir: String): String;
begin
  Result := 'The folder ' + Dir + ' already holds other files. Choose an empty folder, or the '
    + 'folder of an earlier Spyglass install.';
end;

function FolderIsEmpty(Dir: String): Boolean;
var
  Found: TFindRec;
begin
  Result := True;
  if FindFirst(AddBackslash(Dir) + '*', Found) then
  begin
    try
      repeat
        if (Found.Name <> '.') and (Found.Name <> '..') then
          Result := False;
      until (not Result) or (not FindNext(Found));
    finally
      FindClose(Found);
    end;
  end;
end;

{ ---- desktop.json: a small reader for the three keys, and the writer ---- }

{ Index of the first character of Key's value in Json, or 0 when the key is absent. }
function ValueStart(Json, Key: String): Integer;
var
  I: Integer;
begin
  Result := 0;
  I := Pos('"' + Key + '"', Json);
  if I = 0 then
    Exit;
  I := I + Length(Key) + 2;
  while (I <= Length(Json)) and ((Json[I] = ' ') or (Json[I] = ':') or (Json[I] = #9)
      or (Json[I] = #10) or (Json[I] = #13)) do
    I := I + 1;
  if I <= Length(Json) then
    Result := I;
end;

{ Key's text value with JSON escapes undone; '' when absent, null or not text. }
function JsonText(Json, Key: String): String;
var
  I: Integer;
  C: Char;
begin
  Result := '';
  I := ValueStart(Json, Key);
  if (I = 0) or (Json[I] <> '"') then
    Exit;
  I := I + 1;
  while I <= Length(Json) do
  begin
    C := Json[I];
    if C = '"' then
      Exit;
    if (C = '\') and (I < Length(Json)) then
    begin
      I := I + 1;
      C := Json[I];
      case C of
        'n': C := #10;
        't': C := #9;
        'r': C := #13;
        'b': C := #8;
        'f': C := #12;
        'u':
          begin
            C := Chr(StrToIntDef('$' + Copy(Json, I + 1, 4), 63));
            I := I + 4;
          end;
      end;
    end;
    Result := Result + C;
    I := I + 1;
  end;
  Result := '';  { an unterminated string counts as absent }
end;

function JsonInt(Json, Key: String; Default: Integer): Integer;
var
  I, First: Integer;
begin
  Result := Default;
  I := ValueStart(Json, Key);
  if I = 0 then
    Exit;
  First := I;
  while (I <= Length(Json)) and (Json[I] >= '0') and (Json[I] <= '9') do
    I := I + 1;
  Result := StrToIntDef(Copy(Json, First, I - First), Default);
end;

function JsonString(Value: String): String;
begin
  Result := Value;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
  Result := '"' + Result + '"';
end;

{ Read an existing desktop.json, so an upgrade keeps the data folder, vault and port. }
procedure LoadExistingConfig;
var
  Lines: TArrayOfString;
  Json: String;
  I: Integer;
begin
  ExistingDataDir := '';
  ExistingVault := '';
  ExistingPort := 0;
  if not LoadStringsFromFile(DesktopConfigPath, Lines) then
    Exit;
  Json := '';
  for I := 0 to GetArrayLength(Lines) - 1 do
    Json := Json + Lines[I] + #10;
  ExistingDataDir := JsonText(Json, 'data_dir');
  ExistingVault := JsonText(Json, 'vault_path');
  ExistingPort := JsonInt(Json, 'port', 0);
  if (ExistingPort < 1) or (ExistingPort > 65535) then
    ExistingPort := 0;
end;

{ Write desktop.json as UTF-8 without a byte-order mark, which Python's json reader refuses. }
function WriteDesktopConfig(DataDir, Vault: String; Port: Integer): Boolean;
var
  Lines: TArrayOfString;
  VaultJson: String;
begin
  if Vault = '' then
    VaultJson := 'null'
  else
    VaultJson := JsonString(Vault);
  SetArrayLength(Lines, 5);
  Lines[0] := '{';
  Lines[1] := '  "data_dir": ' + JsonString(DataDir) + ',';
  Lines[2] := '  "vault_path": ' + VaultJson + ',';
  Lines[3] := '  "port": ' + IntToStr(Port);
  Lines[4] := '}';
  Result := ForceDirectories(ExtractFileDir(DesktopConfigPath))
    and SaveStringsToUTF8FileWithoutBOM(DesktopConfigPath, Lines, False);
end;

{ ---- Stopping a running Spyglass, but only one that the desktop app started ---- }

{ One request to the local service. Returns the HTTP status, or 0 when nothing answered. }
function LocalRequest(Method: String; Port: Integer; Path: String; var Body: String): Integer;
var
  Http: Variant;
begin
  Result := 0;
  Body := '';
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.SetProxy(1);  { direct: no proxy may see or answer a local address }
    Http.SetTimeouts(RequestTimeoutMs, RequestTimeoutMs, RequestTimeoutMs, RequestTimeoutMs);
    Http.Open(Method, 'http://127.0.0.1:' + IntToStr(Port) + Path, False);
    Http.Send('');
    Result := Http.Status;
    Body := Http.ResponseText;
  except
    Result := 0;
  end;
end;

function CompactJson(Body: String): String;
begin
  Result := Body;
  StringChangeEx(Result, ' ', '', True);
  StringChangeEx(Result, #9, '', True);
  StringChangeEx(Result, #10, '', True);
  StringChangeEx(Result, #13, '', True);
end;

function IsSpyglassHealth(Body: String): Boolean;
var
  Compact: String;
begin
  Compact := CompactJson(Body);
  Result := (Pos('"status":', Compact) > 0) and (Pos('"version":', Compact) > 0);
end;

{ Only the desktop app's own service says so; a developer start says "developer", and 0.40
  and older say nothing. }
function IsStartedByDesktop(Body: String): Boolean;
begin
  Result := Pos('"started_by":"desktop"', CompactJson(Body)) > 0;
end;

{ How many running programs were started from inside Folder (the installed Python). }
function CountProcessesUnder(Folder: String): Integer;
var
  Locator, Service, Items, Item: Variant;
  I, Count: Integer;
  Prefix: String;
begin
  Result := 0;
  Prefix := AnsiLowercase(AddBackslash(Folder));
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Items := Service.ExecQuery('SELECT ExecutablePath FROM Win32_Process');
    Count := Items.Count;
    for I := 0 to Count - 1 do
    begin
      Item := Items.ItemIndex(I);
      if not VarIsNull(Item.ExecutablePath) then
        if Pos(Prefix, AnsiLowercase(Item.ExecutablePath)) = 1 then
          Result := Result + 1;
    end;
  except
    Result := 0;  { without WMI, the free port alone decides }
  end;
end;

{ Wait until the port is free and no program runs from the install folder, at most StopWaitMs. }
procedure WaitUntilStopped(Port: Integer; var Note: String);
var
  Start: DWORD;
  Body: String;
begin
  Start := GetTickCount;
  repeat
    if (LocalRequest('GET', Port, '/api/health', Body) = 0)
        and (CountProcessesUnder(ExpandConstant('{app}')) = 0) then
    begin
      Note := Note + ' It stopped after ' + IntToStr(GetTickCount - Start) + ' ms.';
      Exit;
    end;
    Sleep(PollMs);
  until GetTickCount - Start >= StopWaitMs;
  Note := Note + ' It was still running after 15 seconds; setup went on.';
end;

{ Stop the Spyglass on Port when, and only when, the desktop app started it. A Spyglass started
  another way (a developer copy, a script, the Obsidian plugin) is left running. }
procedure StopDesktopSpyglass(Port: Integer; ShowWarning: Boolean; var Note: String);
var
  Body: String;
begin
  Note := 'Nothing answered on port ' + IntToStr(Port) + '.';
  if LocalRequest('GET', Port, '/api/health', Body) <> 200 then
    Exit;
  if not IsSpyglassHealth(Body) then
  begin
    Note := 'Another program answers on port ' + IntToStr(Port) + '; it was left alone.';
    Exit;
  end;
  if not IsStartedByDesktop(Body) then
  begin
    Note := 'A Spyglass that the app did not start runs on port ' + IntToStr(Port)
      + '; it was left running.';
    if ShowWarning then
      MsgBox('A Spyglass that was not started by the Spyglass app is running on port '
        + IntToStr(Port) + ', for example from a command line, a script or the Obsidian plugin.'
        + #13#10#13#10 + 'Setup leaves it running. Stop it before you open the installed '
        + 'Spyglass, because only one Spyglass can use the port.', mbInformation, MB_OK);
    Exit;
  end;
  Note := 'Asked the Spyglass app on port ' + IntToStr(Port) + ' to stop.';
  LocalRequest('POST', Port, '/api/shutdown', Body);
  WaitUntilStopped(Port, Note);
end;

{ ---- The steps after the files are copied ---- }

{ Run Exe through cmd.exe without a window, appending all its output to OutFile.
  Returns its exit code, or -1 when it could not be started. }
function RunLogged(Exe, Params, WorkDir, OutFile: String): Integer;
var
  Code: Integer;
begin
  AppendLog('> "' + Exe + '" ' + Params);
  if not Exec(ExpandConstant('{cmd}'),
      '/S /C ""' + Exe + '" ' + Params + ' >> "' + OutFile + '" 2>&1"',
      WorkDir, SW_HIDE, ewWaitUntilTerminated, Code) then
  begin
    AppendLog('Could not start it: ' + SysErrorMessage(Code));
    Result := -1;
    Exit;
  end;
  AppendLog('Exit code ' + IntToStr(Code) + '.');
  Result := Code;
end;

{ The uv settings exist only while uv runs, so the "Open Spyglass now" start cannot inherit them. }
procedure ClearUvEnvironment;
begin
  ClearEnvironmentVariable('UV_PYTHON_INSTALL_DIR', 0);
  ClearEnvironmentVariable('UV_PROJECT_ENVIRONMENT', 0);
  ClearEnvironmentVariable('UV_LINK_MODE', 0);
  ClearEnvironmentVariable('UV_CACHE_DIR', 0);
  ClearEnvironmentVariable('UV_MANAGED_PYTHON', 0);
  ClearEnvironmentVariable('UV_PYTHON_INSTALL_BIN', 0);
  ClearEnvironmentVariable('UV_PYTHON_INSTALL_REGISTRY', 0);
  ClearEnvironmentVariable('UV_COMPILE_BYTECODE', 0);
end;

{ Install Python 3.13 and the locked libraries into the install folder. UV_MANAGED_PYTHON keeps
  uv from building the environment on a Python found elsewhere on the PC, which an uninstall of
  that Python would break. The two INSTALL variables keep uv from adding a python.exe to the
  user's PATH folder or a Python entry to the registry: nothing may point into the install folder
  after an uninstall. Copies, not links, so nothing points into the deleted cache. Compiling the
  libraries here keeps that work out of the first start, which must open the interface within
  30 seconds. }
function InstallEnvironment: Boolean;
var
  Cache: String;
  Code: Integer;
begin
  Cache := ExpandConstant('{tmp}\uv-cache');
  SetEnvironmentVariable('UV_PYTHON_INSTALL_DIR', ExpandConstant('{app}\python'));
  SetEnvironmentVariable('UV_PROJECT_ENVIRONMENT', ExpandConstant('{app}\.venv'));
  SetEnvironmentVariable('UV_LINK_MODE', 'copy');
  SetEnvironmentVariable('UV_CACHE_DIR', Cache);
  SetEnvironmentVariable('UV_MANAGED_PYTHON', '1');
  SetEnvironmentVariable('UV_PYTHON_INSTALL_BIN', '0');
  SetEnvironmentVariable('UV_PYTHON_INSTALL_REGISTRY', '0');
  SetEnvironmentVariable('UV_COMPILE_BYTECODE', '1');
  Code := RunLogged(ExpandConstant('{app}\uv.exe'), 'sync --frozen --no-dev --python 3.13',
    ExpandConstant('{app}'), InstallLogPath);
  ClearUvEnvironment;
  DelTree(Cache, True, True, True);
  Result := Code = 0;
end;

{ The installed Spyglass's own data folder check: 0 fine, 3 older data, 4 newer data.
  It only reads the folder. Message receives what it printed. }
function RunFolderCheck(DataDir: String; var Message: String): Integer;
var
  OutFile: String;
  Lines: TArrayOfString;
  I: Integer;
begin
  OutFile := ExpandConstant('{tmp}\folder-check.txt');
  DeleteFile(OutFile);
  Result := RunLogged(ExpandConstant('{app}\.venv\Scripts\python.exe'),
    '-X utf8 -m spyglass_service.desktop --check-data-dir "' + ArgPath(DataDir) + '"',
    ExpandConstant('{app}'), OutFile);
  Message := '';
  if LoadStringsFromFile(OutFile, Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
    begin
      AppendLog(Lines[I]);
      Message := Trim(Message + ' ' + Lines[I]);
    end;
end;

procedure CreateStartMenuEntry;
begin
  try
    CreateShellLink(ExpandConstant('{userprograms}\Spyglass.lnk'), 'Open Spyglass', PythonW,
      '-m spyglass_service.desktop', ExpandConstant('{app}'),
      ExpandConstant('{app}\installer\spyglass.ico'), 0, SW_SHOWNORMAL);
    AppendLog('Created the Start-menu entry.');
  except
    AppendLog('Could not create the Start-menu entry: ' + GetExceptionMessage);
  end;
end;

{ Remove the start-up entry, but only when it starts this installed copy. }
procedure RemoveAutostartIfOurs;
var
  Value: String;
begin
  if RegQueryStringValue(HKCU, RunKey, RunValue, Value)
      and (Pos(AnsiLowercase(AddBackslash(ExpandConstant('{app}'))), AnsiLowercase(Value)) > 0) then
  begin
    RegDeleteValue(HKCU, RunKey, RunValue);
    Log('Removed the start-up entry.');
  end;
end;

{ The same value the app writes from the tray or Settings, so all three always agree. }
procedure ApplyAutostart(Enable: Boolean);
begin
  if not Enable then
  begin
    RemoveAutostartIfOurs;
    Exit;
  end;
  if RegWriteStringValue(HKCU, RunKey, RunValue,
      '"' + PythonW + '" -m spyglass_service.desktop --background') then
    AppendLog('Start with Windows is on.')
  else
    AppendLog('Could not switch on Start with Windows.');
end;

{ The task that the old start-up script registered would start a second Spyglass at sign-in. }
procedure RemoveOldScheduledTask;
var
  Schtasks: String;
begin
  Schtasks := ExpandConstant('{sys}\schtasks.exe');
  if RunLogged(Schtasks, '/Query /TN Spyglass', '', InstallLogPath) = 0 then
    RunLogged(Schtasks, '/Delete /TN Spyglass /F', '', InstallLogPath);
end;

{ Run the windowless Python once, loading every Spyglass and uvicorn module, while Setup still
  runs. Windows inspects a new program closely the first time it runs, which made the first start
  after an install take over 30 seconds; later starts take a few. It must be pythonw.exe, the
  program the Start-menu entry runs. The script only imports and writes its summary to OutFile:
  nothing is started and no data is touched. -I keeps the install folder off the module path. A
  failure only costs time at the first start. }
procedure WarmUpFirstStart;
var
  Script, OutFile: String;
  Lines: TArrayOfString;
  Code, I: Integer;
begin
  Script := ExpandConstant('{tmp}\spyglass_warmup.py');
  OutFile := ExpandConstant('{tmp}\spyglass_warmup.txt');
  SetArrayLength(Lines, 15);
  Lines[0] := 'import importlib, pkgutil, sys, time';
  Lines[1] := 'import spyglass_service, uvicorn';
  Lines[2] := 'started = time.perf_counter()';
  Lines[3] := 'failed = []';
  Lines[4] := 'for package in (spyglass_service, uvicorn):';
  Lines[5] := '    prefix = package.__name__ + "."';
  Lines[6] := '    for found in pkgutil.walk_packages(package.__path__, prefix, onerror=failed.append):';
  Lines[7] := '        try:';
  Lines[8] := '            importlib.import_module(found.name)';
  Lines[9] := '        except Exception as exc:';
  Lines[10] := '            failed.append(f"{found.name}: {exc}")';
  Lines[11] := 'seconds = time.perf_counter() - started';
  Lines[12] := 'with open(sys.argv[1], "w", encoding="utf-8") as out:';
  Lines[13] := '    out.write(f"Loaded {len(sys.modules)} modules in {seconds:.1f} s.\n")';
  Lines[14] := '    out.write(f"Not loaded: {failed or ''none''}\n")';
  if not SaveStringsToUTF8FileWithoutBOM(Script, Lines, False) then
  begin
    AppendLog('Could not write the warm-up script; the first start will take longer.');
    Exit;
  end;
  AppendLog('> "' + PythonW + '" -I -X utf8 "' + Script + '"');
  if not Exec(PythonW, '-I -X utf8 "' + Script + '" "' + OutFile + '"', ExpandConstant('{app}'),
      SW_HIDE, ewWaitUntilTerminated, Code) then
    Code := -1;
  if LoadStringsFromFile(OutFile, Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
      AppendLog(Lines[I]);
  AppendLog('Exit code ' + IntToStr(Code) + '.');
  if Code <> 0 then
    AppendLog('The warm-up failed; the first start will take longer.');
end;

procedure StopWithMessage(ExitCode: Integer; Message: String);
begin
  SetupFailure := Message;
  CustomExitCode := ExitCode;
  AppendLog('Stopped: ' + Message);
  SuppressibleMsgBox(Message, mbError, MB_OK, IDOK);
end;

{ Environment, folder check, settings file, Start menu, start-up entry, warm-up: in that order,
  and a refused data folder stops before desktop.json is written. }
procedure SetUpSpyglass;
var
  DataDir, Vault, Message: String;
  Ready: Boolean;
  Code: Integer;
begin
  DataDir := RemoveBackslashUnlessRoot(Trim(DataDirPage.Values[0]));
  Vault := RemoveBackslashUnlessRoot(Trim(VaultPage.Values[0]));
  AppendLog('--- Spyglass {#AppVersion} setup, '
    + GetDateTimeString('yyyy/mm/dd hh:nn:ss', '-', ':') + ' ---');
  AppendLog(StopNote);
  WizardForm.FilenameLabel.Caption := '';
  WizardForm.StatusLabel.Caption :=
    'Setting up Python and the libraries Spyglass needs. This takes a few minutes...';
  WizardForm.ProgressGauge.Style := npbstMarquee;
  Ready := InstallEnvironment;
  WizardForm.ProgressGauge.Style := npbstNormal;
  if not Ready then
  begin
    StopWithMessage(ExitSetupFailed, 'Setup could not prepare Python and the libraries '
      + 'Spyglass needs. The details are in ' + InstallLogPath + '.');
    Exit;
  end;

  WizardForm.StatusLabel.Caption := 'Checking the data folder...';
  Code := RunFolderCheck(DataDir, Message);
  if Code <> 0 then
  begin
    if (Code = 3) or (Code = 4) then
    begin
      if Message = '' then
        Message := 'This Spyglass cannot use the data folder ' + DataDir + '.';
      StopWithMessage(100 + Code, Message + #13#10#13#10 + 'Nothing in that folder was '
        + 'changed. Run the installer again and choose another data folder.');
    end
    else
      StopWithMessage(ExitSetupFailed, 'Setup could not check the data folder ' + DataDir
        + '. The details are in ' + InstallLogPath + '.');
    Exit;
  end;

  WizardForm.StatusLabel.Caption := 'Saving the settings...';
  if not ForceDirectories(DataDir) then
  begin
    StopWithMessage(ExitSetupFailed, 'Setup could not create the data folder ' + DataDir + '.');
    Exit;
  end;
  if not WriteDesktopConfig(DataDir, Vault, ConfiguredPort) then
  begin
    StopWithMessage(ExitSetupFailed, 'Setup could not write ' + DesktopConfigPath + '.');
    Exit;
  end;
  AppendLog('Wrote ' + DesktopConfigPath + ': data folder ' + DataDir + ', port '
    + IntToStr(ConfiguredPort) + '.');
  CreateStartMenuEntry;
  ApplyAutostart(AutostartPage.Values[0]);
  RemoveOldScheduledTask;
  WizardForm.StatusLabel.Caption := 'Preparing Spyglass for its first start...';
  WarmUpFirstStart;
  AppendLog('Spyglass is ready.');
end;

{ ---- Wizard pages and Setup events ---- }

{ The data folder: /DATADIR= for test installs, then the existing settings, then the default. }
function InitialDataDir: String;
begin
  Result := ExpandConstant('{param:DATADIR|}');
  if Result = '' then
    Result := ExistingDataDir;
  if Result = '' then
    Result := ExpandConstant('{localappdata}\Spyglass\data');
end;

{ /AUTOSTART=1 or 0 for test installs; otherwise the start-up entry itself is the setting. }
function InitialAutostart: Boolean;
var
  Param: String;
begin
  Param := ExpandConstant('{param:AUTOSTART|}');
  if Param = '1' then
    Result := True
  else if Param = '0' then
    Result := False
  else
    Result := RegValueExists(HKCU, RunKey, RunValue);
end;

procedure BrowseVault(Sender: TObject);
var
  Dir: String;
begin
  Dir := VaultPage.Values[0];
  if BrowseForFolder('Choose your Obsidian vault folder.', Dir, False) then
    VaultPage.Values[0] := Dir;
end;

{ The port: /PORT= for test installs, then the existing settings, then 7777. }
function InitializeSetup: Boolean;
var
  Param: String;
begin
  Result := True;
  LoadExistingConfig;
  Param := ExpandConstant('{param:PORT|}');
  if Param <> '' then
  begin
    ConfiguredPort := StrToIntDef(Param, 0);
    if (ConfiguredPort < 1) or (ConfiguredPort > 65535) then
    begin
      SuppressibleMsgBox('The port "' + Param + '" is not a number from 1 to 65535.',
        mbError, MB_OK, IDOK);
      Result := False;
    end;
  end
  else if ExistingPort > 0 then
    ConfiguredPort := ExistingPort
  else
    ConfiguredPort := DefaultPort;
end;

procedure InitializeWizard;
var
  Browse: TNewButton;
begin
  DataDirPage := CreateInputDirPage(wpSelectDir, 'Data folder',
    'Where should Spyglass keep its data?',
    'Spyglass keeps its database, logs and backups in this folder. The folder stays when '
    + 'Spyglass is uninstalled, and an upgrade keeps using it.', False, '');
  DataDirPage.Add('');
  DataDirPage.Values[0] := InitialDataDir;

  VaultPage := CreateInputQueryPage(DataDirPage.ID, 'Obsidian vault (optional)',
    'Which Obsidian vault should Spyglass file notes into?',
    'Leave this empty if you do not use Obsidian. You can set it later in Settings.');
  VaultPage.Add('Vault folder:', False);
  VaultPage.Values[0] := ExistingVault;
  Browse := TNewButton.Create(VaultPage);
  Browse.Parent := VaultPage.Surface;
  Browse.Caption := 'Browse...';
  Browse.Left := VaultPage.Edits[0].Left;
  Browse.Top := VaultPage.Edits[0].Top + VaultPage.Edits[0].Height + ScaleY(8);
  Browse.Width := WizardForm.NextButton.Width;
  Browse.Height := WizardForm.NextButton.Height;
  Browse.OnClick := @BrowseVault;

  AutostartPage := CreateInputOptionPage(VaultPage.ID, 'Start with Windows',
    'Should Spyglass start when you sign in to Windows?',
    'Spyglass then waits in the notification area without opening the browser. You can '
    + 'change this later from its tray icon or in Settings.', False, False);
  AutostartPage.Add('Start Spyglass when I sign in to Windows');
  AutostartPage.Values[0] := InitialAutostart;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Vault: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    { An upgrade and an uninstall delete the program folders they made, so a folder that holds
      other files (a repository clone, say) is refused unless it is the earlier install. }
    if DirExists(WizardDirValue) and not FolderIsEmpty(WizardDirValue)
        and not IsEarlierInstall(WizardDirValue) then
    begin
      SuppressibleMsgBox(ForeignFolderMessage(WizardDirValue), mbError, MB_OK, IDOK);
      Result := False;
    end;
  end
  else if CurPageID = DataDirPage.ID then
  begin
    { An uninstall or upgrade replaces the program folder, so the data must live elsewhere. }
    if IsInside(DataDirPage.Values[0], WizardDirValue) then
    begin
      SuppressibleMsgBox('Choose a data folder outside the program folder ' + WizardDirValue
        + ', so that an upgrade or an uninstall can never touch your data.',
        mbError, MB_OK, IDOK);
      Result := False;
    end;
  end
  else if CurPageID = VaultPage.ID then
  begin
    Vault := Trim(VaultPage.Values[0]);
    if (Vault <> '') and not DirExists(Vault) and not WizardSilent then
    begin
      MsgBox('The folder ' + Vault + ' does not exist. Choose your vault folder, or leave '
        + 'the field empty.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  Vault, Autostart: String;
begin
  Vault := Trim(VaultPage.Values[0]);
  if Vault = '' then
    Vault := '(none; it can be set later in Settings)';
  if AutostartPage.Values[0] then
    Autostart := 'yes'
  else
    Autostart := 'no';
  Result := MemoDirInfo + NewLine + NewLine
    + 'Data folder:' + NewLine + Space + DataDirPage.Values[0] + NewLine + NewLine
    + 'Obsidian vault:' + NewLine + Space + Vault + NewLine + NewLine
    + 'Start with Windows: ' + Autostart + NewLine
    + 'Port: ' + IntToStr(ConfiguredPort);
end;

{ Before any file is replaced: refuse a folder that holds other files, then stop the installed
  app if it runs (never another Spyglass). The folder page is skipped on an upgrade while /DIR
  still applies, so the folder is checked here, where every install passes. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Dir: String;
begin
  Result := '';
  Dir := ExpandConstant('{app}');
  if DirExists(Dir) and not FolderIsEmpty(Dir) and not IsEarlierInstall(Dir) then
  begin
    Result := ForeignFolderMessage(Dir);
    Exit;
  end;
  StopDesktopSpyglass(ConfiguredPort, not WizardSilent, StopNote);
  Log(StopNote);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SetUpSpyglass;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and (SetupFailure <> '') then
    WizardForm.FinishedLabel.Caption := 'Spyglass is installed but not set up yet. '
      + SetupFailure;
end;

{ Hides "Open Spyglass now" when a step after the copy failed. }
function SetupSucceeded: Boolean;
begin
  Result := SetupFailure = '';
end;

function GetCustomSetupExitCode: Integer;
begin
  Result := CustomExitCode;
end;

{ Delete a folder that uv made inside the install folder. Its deepest files can pass the old
  260-character path limit, which the uninstaller's own delete cannot handle; rd can, through a
  \\?\ path. }
procedure RemoveDeepFolder(Folder: String);
var
  Code: Integer;
begin
  if not DirExists(Folder) then
    Exit;
  if Exec(ExpandConstant('{cmd}'), '/C rd /s /q "\\?\' + RemoveBackslash(Folder) + '"', '',
      SW_HIDE, ewWaitUntilTerminated, Code) then
    Log('Removed ' + Folder + ' (rd exit code ' + IntToStr(Code) + ').')
  else
    Log('Could not start rd for ' + Folder + ': ' + SysErrorMessage(Code));
end;

{ Uninstall: stop the app if it runs, remove its start-up entry; keep the data and desktop.json. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Note, Where: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    LoadExistingConfig;
    if ExistingPort > 0 then
      StopDesktopSpyglass(ExistingPort, False, Note)
    else
      StopDesktopSpyglass(DefaultPort, False, Note);
    Log(Note);
    RemoveAutostartIfOurs;
    RemoveDeepFolder(ExpandConstant('{app}\.venv'));
    RemoveDeepFolder(ExpandConstant('{app}\python'));
  end;
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    if ExistingDataDir <> '' then
      Where := 'Your data stays in ' + ExistingDataDir + ', and the settings in '
        + DesktopConfigPath + '.'
    else
      Where := 'Your data folder was left in place.';
    MsgBox('Spyglass was removed. ' + Where + ' Delete them yourself if you no longer need '
      + 'them; installing Spyglass again uses them.', mbInformation, MB_OK);
  end;
end;
