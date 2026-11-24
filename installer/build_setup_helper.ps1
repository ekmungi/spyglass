# Compile SpyglassSetup.exe, the helper program the MSI installer runs for the steps Windows
# Installer cannot do itself (stopping Spyglass, removing the old installer's copy, building the
# Python environment), from the C# files in installer\setup. Uses the C# compiler that comes with
# the .NET Framework 4.x, which Windows 10 and 11 include, so no build tool has to be installed.
# The local build and the release workflow both run this script:
#   installer\build_setup_helper.ps1 -Version 0.42.0
param(
    # The release version, digits only (x.y.z); it becomes the program's file and product version.
    [Parameter(Mandatory = $true)][string]$Version,
    # Where to write the program; by default installer\SpyglassSetup.exe, where the MSI project looks.
    [string]$OutFile = "",
    # The compiler; by default where the .NET Framework 4.x puts its 64-bit compiler.
    [string]$CscPath = ""
)

$ErrorActionPreference = "Stop"
# Defaults are filled in here, not in param(): Windows PowerShell 5.1 leaves $PSScriptRoot empty there.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $OutFile) { $OutFile = Join-Path $here "SpyglassSetup.exe" }
if (-not $CscPath) { $CscPath = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe" }

# Say why the build stopped, on standard error, and end the script with a non-zero code.
function Stop-Build([string]$Message, [int]$Code = 1) {
    [Console]::Error.WriteLine($Message)
    exit $Code
}

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Stop-Build "Version '$Version' is not a version such as 0.42.0."
}
if (-not (Test-Path -LiteralPath $CscPath -PathType Leaf)) {
    Stop-Build ("The C# compiler was not found at $CscPath. It comes with the .NET Framework 4.8, " +
        "which Windows 10 and 11 include; on another machine, pass its path with -CscPath.")
}

$sources = @(Get-ChildItem -LiteralPath (Join-Path $here "setup") -Filter "*.cs" | ForEach-Object { $_.FullName })
if ($sources.Count -eq 0) {
    Stop-Build "No C# files were found in $(Join-Path $here 'setup')."
}
# The compiler turns these attributes into the version details Explorer and the MSI log show.
$versionInfo = @"
using System.Reflection;
[assembly: AssemblyTitle("Spyglass Setup")]
[assembly: AssemblyDescription("Spyglass Setup")]
[assembly: AssemblyProduct("Spyglass Setup")]
[assembly: AssemblyCompany("ekmungi")]
[assembly: AssemblyVersion("$Version.0")]
[assembly: AssemblyFileVersion("$Version.0")]
[assembly: AssemblyInformationalVersion("$Version")]
"@
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("spyglass-setup-helper-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $versionFile = Join-Path $work "VersionInfo.cs"
    Set-Content -LiteralPath $versionFile -Value $versionInfo -Encoding UTF8
    $outDir = Split-Path -Parent $OutFile
    if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
        New-Item -ItemType Directory -Path $outDir | Out-Null
    }
    # A windowless program: it must never open a console of its own while Windows Installer runs it.
    & $CscPath /nologo /target:winexe /platform:anycpu /optimize+ "/out:$OutFile" @sources $versionFile
    if ($LASTEXITCODE -ne 0) {
        Stop-Build "The C# compiler stopped with exit code $LASTEXITCODE." $LASTEXITCODE
    }
    Write-Output "Built $OutFile (Spyglass Setup $Version)."
}
finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
