; A throwaway Inno Setup installer for one test: does Windows show a per-user app in the Start
; menu straight away when Inno creates the Start-menu entry itself, from [Icons] as VS Code's
; installer does, with an app ID (System.AppUserModel.ID) as Opera's entry has? The Spyglass
; installer instead creates its entry from code, without an app ID. One small program, installed
; for the current user only, without administrator rights.

[Setup]
AppId={{81B1D192-FC2C-43DC-9D9C-3DB06AE6D4F5}
AppName=Spyglass Probe Inno
AppVersion=0.0.3
AppPublisher=ekmungi
AppPublisherURL=https://github.com/ekmungi/spyglass
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Spyglass Probe Inno
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableWelcomePage=no
SetupIconFile=..\spyglass.ico
UninstallDisplayIcon={app}\SpyglassProbeInno.exe
OutputDir=out
OutputBaseFilename=SpyglassProbeInno
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "SpyglassProbeInno.exe"; DestDir: "{app}"

[Icons]
Name: "{autoprograms}\Spyglass Probe Inno"; Filename: "{app}\SpyglassProbeInno.exe"; WorkingDir: "{app}"; AppUserModelID: "ekmungi.SpyglassProbeInno"
