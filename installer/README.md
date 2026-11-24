# Building the Windows installer

Spyglass for Windows is a per-user Windows Installer package, `Spyglass-<version>.msi`, built with
[WiX](https://wixtoolset.org/) 5.0.2, the last release under the plain open-source licence. The
release job in `.github/workflows/release.yml` builds it for every version tag and adds it to the
GitHub release. It also builds `Spyglass-Setup-<version>.exe`, a WiX setup program around the
package, which it attaches to the workflow run only: it is published once a test install has shown
that it, too, puts Spyglass in the Start menu at once.

Why an MSI: Windows lists an app in the Start menu and in Settings > Installed apps at once when
its Start-menu entry is made by Windows Installer and carries an app ID. The entries that the
earlier Inno Setup installer made never appeared there. The package's entry carries the app ID
`ekmungi.Spyglass`.

To try the GitHub build without publishing anything, push a test tag: the code's version plus
`-testN`, for example `0.42.0-test1`. The job builds everything exactly as for a release, creates
no release, and attaches the `.msi` and the `.exe` to the workflow run, where they can be
downloaded from the run's page for seven days. Delete the test tag afterwards with
`git push origin :refs/tags/0.42.0-test1`.

## The parts

| File | What it is |
|------|------------|
| `spyglass.wxs` | The package: files, Start-menu entry, choices, setup steps and pages. |
| `harvest.py` | Writes `obj\files.wxs`, the list of program files (one component per folder), for each build. |
| `bundle.wxs` | The setup `.exe` around the package; it shows the package's own pages. |
| `license.rtf` | The licence page's text. |
| `launcher\Spyglass.cs`, `build_launcher.ps1` | `Spyglass.exe`, the program every starter opens. |
| `setup\*.cs`, `build_setup_helper.ps1` | `SpyglassSetup.exe`, the helper the package runs for its setup steps. |
| `build_msi.ps1` | Builds the package and the setup `.exe`. |
| `spyglass.ico`, `make_icon.py` | The icon, and the script that makes it from the extension's icon. |

The steps after Python exists run in Spyglass's own Python, in
`src/spyglass_service/desktop/setup_steps.py`, so the test suite covers them.

## What you need

- Windows 10 or 11.
- The [.NET SDK](https://dotnet.microsoft.com/download) 8 or newer, for the `dotnet` command, and
  WiX with its three extensions, once per machine:

  ```
  dotnet tool install --global wix --version 5.0.2
  wix extension add -g WixToolset.UI.wixext/5.0.2 WixToolset.Util.wixext/5.0.2 WixToolset.BootstrapperApplications.wixext/5.0.2
  ```
- Node.js, to build the interface, as for a developer install, and Python 3.12 or newer for
  `harvest.py` (any Python; it uses only the standard library).
- The pinned `uv.exe`. The release job downloads uv 0.10.9 and checks it against the SHA-256 in
  `release.yml`. For a local build, copy a `uv.exe` of that version into this folder. The file is
  listed in `.gitignore` and is never committed.
- The C# compiler of the .NET Framework 4.x, which Windows 10 and 11 include at
  `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`. It compiles `Spyglass.exe` and
  `SpyglassSetup.exe`.

## Build

From the repository root:

```
cd frontend
npm ci
npm run build
cd ..
copy %USERPROFILE%\.local\bin\uv.exe installer\uv.exe
powershell -ExecutionPolicy Bypass -File installer\build_launcher.ps1 -Version 0.42.0
powershell -ExecutionPolicy Bypass -File installer\build_setup_helper.ps1 -Version 0.42.0
powershell -ExecutionPolicy Bypass -File installer\build_msi.ps1 -Version 0.42.0
```

The package and the setup program are written to `installer\Output\Spyglass-0.42.0.msi` and
`installer\Output\Spyglass-Setup-0.42.0.exe`, which git ignores. `build_msi.ps1` stops when
`Spyglass.exe` or `SpyglassSetup.exe` is missing or carries another version, so a local build
cannot ship a program from an earlier build.

### Spyglass.exe, the launcher

`Spyglass.exe` is the program at the root of the install folder that the Start-menu entry, the Start
with Windows entry and "Open Spyglass now" all open. It is a short C# program,
`installer\launcher\Spyglass.cs`, that starts `.venv\Scripts\pythonw.exe -m spyglass_service.desktop`
in the install folder with the arguments it was given (`--background` for Start with Windows),
shows no console window and waits until Spyglass ends, so Task Manager shows Spyglass with the
Python processes under it. When the venv's `pythonw.exe`, or the Python that `.venv\pyvenv.cfg`
names, is missing, it says which file is missing and asks you to run setup again.

### SpyglassSetup.exe, the setup helper

`SpyglassSetup.exe <command> --install-dir <folder> [--ui <level>]` does the setup steps that are
programs. The package passes its user-interface level, and the helper shows a message box only
with setup's full or reduced pages. Every step is logged to `%LOCALAPPDATA%\Spyglass\install.log`.

| Command | When | What it does |
|---------|------|--------------|
| `prepare` | Before Windows Installer looks at the files | Stops a Spyglass the desktop app started, refuses to go on while a program still runs from the install folder, and removes a Spyglass that the old Inno Setup installer put on this PC (its data folder and settings stay). |
| `environment` | After the files are copied | Runs `uv sync --frozen --no-dev --python 3.13` with `--extra pdf` and `--extra local-ai` when those parts are ticked, then Spyglass's own setup steps. A uv failure stops setup, which then undoes everything. |
| `uninstall` | Before the files are removed | Stops Spyglass, undoes what setup added (start-up entry, connector, engine) and deletes the Python environment. |
| `remove-environment` | When setup is undone | Deletes `.venv`, `python` and the `__pycache__` folders. |

## What setup does

1. It installs into `%LOCALAPPDATA%\Programs\Spyglass`, the folder 0.41.1 used, and needs no
   administrator rights. Spyglass appears in the Start menu and in Settings > Installed apps.
2. It offers these choices: Start with Windows (ticked only when the start-up entry exists), a
   desktop shortcut, PDF reading, the local AI model, YouTube transcripts, the Claude Code connector
   (ticked when Claude Code is found) and one browser-extension choice for each Chromium browser it
   finds. Each ticked part writes one value under `HKCU\Software\ekmungi\Spyglass\Features`.
3. `prepare` runs, then Windows Installer copies the files and makes the links, then `environment`
   builds Python. Spyglass's own setup steps then write `desktop.json` naming no data folder when
   none exists, apply Start with Windows, add the Claude Code connector (never replacing a connector
   named spyglass that points elsewhere), install the yt-transcribe engine from one pinned commit,
   remove the old "Spyglass" scheduled task, note the browsers for the extension guide and load
   every module once, so that the first start is quick. A choice is applied only when it changed
   since the last run, so a later Modify never undoes what you changed in the app.
4. The last page offers "Open Spyglass now". On a fresh install Spyglass opens on a page that asks
   for the data folder and the vault.

Modify in Settings > Installed apps, or opening the package again, adds and removes parts. An
upgrade keeps the Python environment and builds on it. Uninstall keeps the data folder and
`desktop.json`.

## Checking the package without installing it

`tests/desktop/test_msi_package.py` checks the WiX source (per-user scope, the app ID, the choices
and when each setup step runs), and `tests/desktop/test_setup_helper_exe.py` builds the helper and
runs every command against stand-in programs. WiX itself runs only where it is installed.

For a test install, use a PC or a virtual machine without a real Spyglass, because every install
shares one package identity: a test install upgrades the real one. A silent install with a log:

```
msiexec /i Spyglass-0.42.0.msi /qn /l*v C:\scratch\msi.log
```

`ADDLOCAL=Spyglass,PdfReading,LocalAi` chooses the parts on the command line. Uninstall with
`msiexec /x Spyglass-0.42.0.msi /qn`.
