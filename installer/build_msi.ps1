# Build the Spyglass MSI (installer\spyglass.wxs) and the setup .exe around it (installer\bundle.wxs)
# with WiX 5.0.2. The release workflow and a local build both run it from any folder:
#   installer\build_msi.ps1 -Version 0.42.0
# Before it: npm run build in frontend, the pinned uv.exe copied to installer\uv.exe, and the two
# programs compiled for the same version:
#   installer\build_launcher.ps1 -Version 0.42.0
#   installer\build_setup_helper.ps1 -Version 0.42.0
# WiX and its three extensions, once per machine (the .NET SDK provides the dotnet command):
#   dotnet tool install --global wix --version 5.0.2
#   wix extension add -g WixToolset.UI.wixext/5.0.2 WixToolset.Util.wixext/5.0.2 WixToolset.BootstrapperApplications.wixext/5.0.2
param(
    # The release version, digits only (x.y.z); Windows Installer needs it as digits.
    [Parameter(Mandatory = $true)][string]$Version,
    # The WiX command; by default wix from PATH.
    [string]$Wix = "wix",
    # The Python that runs installer\harvest.py; by default python, else the py launcher.
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
# Paths are worked out in the body: Windows PowerShell 5.1 leaves $PSScriptRoot empty in param().
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here

# Say why the build stopped, on standard error, and end the script with a non-zero code.
function Stop-Build([string]$Message) {
    [Console]::Error.WriteLine($Message)
    exit 1
}

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Stop-Build "Version '$Version' is not a version such as 0.42.0."
}
# A program left from an earlier build would carry the wrong version into the package.
$scripts = @{ "Spyglass.exe" = "build_launcher.ps1"; "SpyglassSetup.exe" = "build_setup_helper.ps1" }
foreach ($program in $scripts.Keys) {
    $path = Join-Path $here $program
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Stop-Build "Build $program first: installer\$($scripts[$program]) -Version $Version"
    }
    $found = (Get-Item -LiteralPath $path).VersionInfo.FileVersion
    if ($found -ne "$Version.0") {
        Stop-Build "$program is version $found, not $Version. Build it again: installer\$($scripts[$program]) -Version $Version"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $here "uv.exe") -PathType Leaf)) {
    Stop-Build "Copy the pinned uv.exe to installer\uv.exe first (see installer\README.md)."
}
if (-not $Python) {
    $Python = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "py" }
}

Push-Location $root
try {
    # WiX reads every file path relative to the repository root.
    & $Python installer\harvest.py --out installer\obj\files.wxs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $msi = "installer\Output\Spyglass-$Version.msi"
    & $Wix build -arch x64 -ext WixToolset.UI.wixext -ext WixToolset.Util.wixext `
        -d "Version=$Version" -o $msi installer\spyglass.wxs installer\obj\files.wxs
    if ($LASTEXITCODE -ne 0) { Stop-Build "WiX could not build the MSI (exit code $LASTEXITCODE)." }
    $exe = "installer\Output\Spyglass-Setup-$Version.exe"
    & $Wix build -arch x64 -ext WixToolset.BootstrapperApplications.wixext -d "Version=$Version" -d "MsiPath=$msi" `
        -o $exe installer\bundle.wxs
    if ($LASTEXITCODE -ne 0) { Stop-Build "WiX could not build the setup .exe (exit code $LASTEXITCODE)." }
    Write-Output "Built $msi and $exe."
}
finally {
    Pop-Location
}
