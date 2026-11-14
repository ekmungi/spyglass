# Building the Windows installer

`spyglass.iss` is the Inno Setup script for `Spyglass-Setup-<version>.exe`, the one-file, per-user
installer. The release job in `.github/workflows/release.yml` builds it for every version tag and
adds it to the GitHub release. These are the steps to build and try it on your own PC.

## What you need

- Windows 10 or 11.
- [Inno Setup](https://jrsoftware.org/isinfo.php) 6.3 or newer. The script stops with an error on
  an older compiler.
- Node.js, to build the interface, as for a developer install.
- The pinned `uv.exe`. The release job downloads uv 0.10.9 and checks it against the SHA-256 in
  `release.yml`. For a local build, copy a `uv.exe` of that version into this folder. The file is
  listed in `.gitignore` and is never committed.

## Build

From the repository root:

```
cd frontend
npm ci
npm run build
cd ..
copy %USERPROFILE%\.local\bin\uv.exe installer\uv.exe
iscc /DAppVersion=0.41.0 installer\spyglass.iss
```

The installer is written to `installer\Output\Spyglass-Setup-0.41.0.exe`, which is also ignored by
git. `/DAppVersion` is required; without it the compiler stops.

The icon, `spyglass.ico`, is committed. Make it again only when the extension's icon changes:

```
uv run python installer/make_icon.py
```

## What the installer does

1. It installs into `%LOCALAPPDATA%\Programs\Spyglass` by default and needs no administrator rights.
   It refuses a folder that already holds other files, unless Windows records it as the folder of
   an earlier Spyglass install, because upgrades and the uninstaller replace or delete the program
   folders there.
2. It asks for the data folder (default `%LOCALAPPDATA%\Spyglass\data`), the Obsidian vault
   (optional) and Start with Windows. On an upgrade, the first two come from the existing
   `%LOCALAPPDATA%\Spyglass\desktop.json`.
3. Before it replaces any file, it stops a running Spyglass through its stop address, but only
   when that Spyglass reports that the desktop app started it. A Spyglass started another way, for
   example `python -m spyglass_service` from a clone, is left running, and Setup warns about it.
4. It runs `uv sync --frozen --no-dev --python 3.13` in the install folder. Python goes into
   `python\` and the environment into `.venv\`; uv's cache is a temporary folder that is deleted
   afterwards. The libraries are compiled to bytecode during the install.
5. It runs the data folder check of the installed Spyglass. When the folder holds an older
   Spyglass, or a newer Spyglass has used it, Setup shows the reason and writes no `desktop.json`.
6. It writes `desktop.json`, creates the Start-menu entry "Spyglass", writes the Start with Windows
   entry when it is ticked, and removes the old "Spyglass" scheduled task if one exists.
7. It runs the installed Python once to load every module, so that the first start is quick.

Every step's output goes to `install.log` in the install folder.

The uninstaller stops the desktop app if it runs, removes the Start with Windows entry and deletes
the install folder. The data folder and `desktop.json` stay.

## Trying a scratch install

**Warning: run this recipe only on a PC (or a virtual machine) that has no real Spyglass
installed.** Every install of Spyglass shares one installer identity, so a scratch install replaces
the real install's uninstall entry, its Start-menu entry and its `desktop.json`. Uninstalling the
scratch copy then leaves the real install without an uninstaller or a Start-menu entry, and its
`desktop.json` points at the scratch folder.

A silent install takes the folder, data folder and port on its command line. Use another port and
scratch folders, so a Spyglass you run from the repository stays up:

```
Spyglass-Setup-0.41.0.exe /VERYSILENT /SUPPRESSMSGBOXES /DIR="C:\scratch\app" /DATADIR="C:\scratch\data" /PORT=7790 /LOG="C:\scratch\setup.log"
```

`/AUTOSTART=1` or `/AUTOSTART=0` sets Start with Windows; without it, an upgrade keeps the current
setting. A port or data folder given on the command line wins over the one in `desktop.json`.

The installer always writes the real `%LOCALAPPDATA%\Spyglass\desktop.json`, because the Start-menu
entry reads it. After a test, uninstall with `C:\scratch\app\unins000.exe /VERYSILENT`, then
delete `desktop.json` if it points at the scratch folder.

Setup's exit codes:

| Code | Meaning |
|------|---------|
| 0 | Installed and set up. |
| 7 | Nothing was installed: the install folder holds other files and is not an earlier install. |
| 103 | The data folder holds an older Spyglass; nothing in it was changed. |
| 104 | A newer Spyglass has used the data folder; nothing in it was changed. |
| 110 | The files are installed, but Python, the check or the settings file failed; see `install.log`. |

Codes 1 to 8 are Inno Setup's own, for example 2 when Setup was cancelled; 7 is its code for a
refusal before installing.
