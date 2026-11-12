@echo off
rem Starts the Spyglass service if it is not already running, then opens it in an app-style
rem browser window (no tabs or address bar). Double-click it or pin it to the taskbar.
setlocal EnableExtensions

rem The repository root is the parent of this script's folder (%~dp0 ends with a backslash).
for %%I in ("%~dp0..") do set "ROOT=%%~fI"

rem The port is the service's own setting; 7777 unless SPYGLASS_PORT says otherwise.
if "%SPYGLASS_PORT%"=="" (set "PORT=7777") else (set "PORT=%SPYGLASS_PORT%")
set "URL=http://127.0.0.1:%PORT%"

rem Is the service already answering? curl ships with Windows 10 and later.
curl -s -f -m 2 "%URL%/api/health" >nul 2>&1
if not errorlevel 1 goto open

rem Not running: start it hidden. pythonw has no console window; "start" returns immediately.
if not exist "%ROOT%\.venv\Scripts\pythonw.exe" (
  echo Could not find "%ROOT%\.venv\Scripts\pythonw.exe". Run "uv sync" in "%ROOT%" first.
  pause
  exit /b 1
)
pushd "%ROOT%"
start "" "%ROOT%\.venv\Scripts\pythonw.exe" -m spyglass_service
popd

rem Wait up to 40 seconds for the service to answer before opening the window.
for /l %%N in (1,1,40) do (
  curl -s -f -m 2 "%URL%/api/health" >nul 2>&1 && goto open
  timeout /t 1 /nobreak >nul
)
echo Spyglass did not start within 40 seconds. Check the service log in the data folder.
pause
exit /b 1

:open
rem Prefer Edge (always present on Windows 11), then Chrome; both support --app.
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%EDGE%" (start "" "%EDGE%" --app=%URL% & exit /b 0)
if exist "%CHROME%" (start "" "%CHROME%" --app=%URL% & exit /b 0)
rem No supported browser found: fall back to the default browser in a normal tab.
start "" "%URL%"
exit /b 0
