#Requires -Version 5.1
<#
.SYNOPSIS
  Build the STTMeet Windows installer (Nuitka freeze + Inno Setup).

.DESCRIPTION
  Creates/uses .\venv, fetches the bundled FFmpeg binaries, freezes main.py
  when needed, then compiles installer_output\sttmeet_setup.exe with Inno
  Setup 6.

  Default command (.\scripts\build_windows.cmd) always produces the installer
  unless -SkipInstaller is passed.

.PARAMETER OneFile
  Also produce a single-file exe (slower startup). Default is a standalone folder.

.PARAMETER UpdateDeps
  Force pip install of requirements + Nuitka even if packages are already present.

.PARAMETER UpdateFfmpeg
  Re-download the bundled FFmpeg binaries even if they already exist.

.PARAMETER InstallerOnly
  Skip the Nuitka freeze; package the existing sttmeet.dist\ into the installer.

.PARAMETER SkipInstaller
  Freeze only; do not run Inno Setup.

.PARAMETER UseGcc
  Use Nuitka's default C compiler (gcc/MinGW) instead of MSVC. Not
  recommended: google.genai's generated C exceeds gcc's assembler limits.
  Use only if you have no Visual Studio Build Tools installed.

.EXAMPLE
  .\scripts\build_windows.ps1

.EXAMPLE
  .\scripts\build_windows.ps1 -InstallerOnly

.EXAMPLE
  .\scripts\build_windows.ps1 -UpdateDeps -UpdateFfmpeg

.EXAMPLE
  .\scripts\build_windows.ps1 -UseGcc
#>
[CmdletBinding()]
param(
    [switch]$OneFile,
    [switch]$UpdateDeps,
    [switch]$UpdateFfmpeg,
    [switch]$InstallerOnly,
    [switch]$SkipInstaller,
    [switch]$UseGcc
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

# Where the frozen app looks for its bundled FFmpeg copy
# (see src/config.py :: get_bundled_ffmpeg_dir)
$FfmpegBinDir = Join-Path $RepoRoot "vendor\ffmpeg\bin"
$FfmpegZipUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-BuildDeps([string]$PythonExe) {
    $probe = "import importlib.util; mods=('google.genai','pydub','customtkinter','docx','dotenv','PyInstaller'); missing=[m for m in mods if importlib.util.find_spec(m) is None]; raise SystemExit(1 if missing else 0)"
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $null = & $PythonExe -c $probe 2>&1
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prev
    return $ok
}

function Install-BuildDeps([string]$PythonExe, [string]$Root) {
    Write-Step "Installing dependencies"
    & $PythonExe -m pip install -r (Join-Path $Root "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "requirements.txt install failed." }
}

function Get-AppVersion([string]$Root) {
    $versionFile = Join-Path $Root "src\version.py"
    $text = Get-Content -Path $versionFile -Raw -ErrorAction Stop
    if ($text -match '__version__\s*=\s*"([^"]+)"') {
        return $Matches[1]
    }
    throw "Could not read __version__ from src\version.py"
}

function Get-WindowsFileVersion([string]$SemVer) {
    $core = $SemVer.Trim().TrimStart("v", "V")
    if ($core -match "^(\d+)(?:\.(\d+))?(?:\.(\d+))?") {
        $major = [int]$Matches[1]
        $minor = if ($Matches[2]) { [int]$Matches[2] } else { 0 }
        $patch = if ($Matches[3]) { [int]$Matches[3] } else { 0 }
        return "$major.$minor.$patch.0"
    }
    throw "Invalid semantic version for Windows file version: $SemVer"
}

function Get-FfmpegBinaries([string]$BinDir) {
    return @(
        (Join-Path $BinDir "ffmpeg.exe"),
        (Join-Path $BinDir "ffprobe.exe")
    )
}

function Install-Ffmpeg([string]$Root, [string]$BinDir) {
    <#
      Downloads the Windows FFmpeg essentials build and keeps only ffmpeg.exe
      and ffprobe.exe in vendor\ffmpeg\bin. Those two files are what the
      installer ships; everything else in the archive is discarded.
    #>
    Write-Step "Bundled FFmpeg"

    $binaries = Get-FfmpegBinaries -BinDir $BinDir
    $haveAll = $true
    foreach ($binary in $binaries) {
        if (-not (Test-Path $binary)) { $haveAll = $false }
    }

    if ($haveAll -and -not $UpdateFfmpeg) {
        Write-Host "FFmpeg already present in $BinDir - skipping download"
        return
    }
    if ($haveAll) {
        Write-Host "Forced refresh (-UpdateFfmpeg)"
    }

    $workDir = Join-Path $env:TEMP "sttmeet_ffmpeg"
    if (Test-Path $workDir) {
        Remove-Item -LiteralPath $workDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null

    $zipPath = Join-Path $workDir "ffmpeg.zip"
    Write-Host "Downloading $FfmpegZipUrl"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $FfmpegZipUrl -OutFile $zipPath -UseBasicParsing

    Write-Host "Extracting ffmpeg.exe / ffprobe.exe ..."
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $extractDir = Join-Path $workDir "extracted"
    [IO.Compression.ZipFile]::ExtractToDirectory($zipPath, $extractDir)

    $found = Get-ChildItem -Path $extractDir -Recurse -File -Include "ffmpeg.exe", "ffprobe.exe"
    if (-not $found) {
        throw "ffmpeg.exe / ffprobe.exe not found inside the downloaded archive."
    }

    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    foreach ($name in @("ffmpeg.exe", "ffprobe.exe")) {
        $match = $found | Where-Object { $_.Name -eq $name } | Select-Object -First 1
        if (-not $match) { throw "$name missing from the downloaded FFmpeg archive." }
        Copy-Item -LiteralPath $match.FullName -Destination (Join-Path $BinDir $name) -Force
        Write-Host "  -> $name"
    }

    Remove-Item -LiteralPath $workDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "FFmpeg ready in $BinDir"
}

function Find-ISCC {
    $candidates = @(
        (Join-Path $env:LocalAppData "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles} "Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    return $null
}

function Build-Installer([string]$Root, [string]$Version) {
    Write-Step "Building Windows installer (Inno Setup)"
    $distExe = Join-Path $Root "sttmeet.dist\sttmeet.exe"
    if (-not (Test-Path $distExe)) {
        throw "Missing $distExe - run a full build first (without -InstallerOnly)."
    }
    foreach ($binary in (Get-FfmpegBinaries -BinDir $FfmpegBinDir)) {
        if (-not (Test-Path $binary)) {
            throw "Missing bundled FFmpeg binary: $binary. Re-run the build without -InstallerOnly."
        }
    }
    $iscc = Find-ISCC
    if (-not $iscc) {
        throw "Inno Setup 6 not found (ISCC.exe). Install from https://jrsoftware.org/isinfo.php then re-run. Expected: installer_output\sttmeet_setup.exe"
    }
    $iss = Join-Path $Root "scripts\sttmeet_setup.iss"
    if (-not (Test-Path $iss)) { throw "Missing Inno script: $iss" }
    $outDir = Join-Path $Root "installer_output"
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    Write-Host "ISCC: $iscc"
    Write-Host "Version: $Version"
    $fileVersion = Get-WindowsFileVersion $Version
    Write-Host "Windows file version: $fileVersion"
    & $iscc "/DMyAppVersion=$Version" "/DMyFileVersion=$fileVersion" "/DRepoRoot=$Root" $iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed (exit $LASTEXITCODE)." }
    $setup = Join-Path $outDir "sttmeet_setup.exe"
    if (-not (Test-Path $setup)) {
        throw "Installer was not created at $setup"
    }
    return $setup
}

if ($env:OS -ne "Windows_NT") {
    throw "This script builds a Windows installer and must run on Windows."
}

$AppVersion = Get-AppVersion -Root $RepoRoot
$WinFileVersion = Get-WindowsFileVersion $AppVersion
$ExeStandalone = Join-Path $RepoRoot "sttmeet.dist\sttmeet.exe"

if (-not $InstallerOnly) {
    $PythonCmd = $null
    foreach ($candidate in @("python", "py")) {
        try {
            $ver = & $candidate --version 2>&1
            if ($LASTEXITCODE -eq 0 -or $ver -match "Python") {
                $PythonCmd = $candidate
                break
            }
        } catch {
            continue
        }
    }
    if (-not $PythonCmd) {
        throw "Python 3.10+ not found on PATH. Install Python and retry."
    }

    $VenvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"

    Write-Step "Virtual environment"
    if (-not (Test-Path $VenvPython)) {
        Write-Host "Creating .\venv ..."
        & $PythonCmd -m venv (Join-Path $RepoRoot "venv")
        if ($LASTEXITCODE -ne 0) { throw "Failed to create venv." }
    } else {
        Write-Host "Using existing .\venv"
    }

    Write-Step "Checking dependencies"
    if ($UpdateDeps) {
        Write-Host "Forced refresh (-UpdateDeps)"
        Install-BuildDeps -PythonExe $VenvPython -Root $RepoRoot
    } elseif (Test-BuildDeps -PythonExe $VenvPython) {
        Write-Host "All build packages present - skipping pip install"
    } else {
        Write-Host "Missing packages detected - installing"
        Install-BuildDeps -PythonExe $VenvPython -Root $RepoRoot
        if (-not (Test-BuildDeps -PythonExe $VenvPython)) {
            throw "Dependencies still missing after install. Check pip output above."
        }
    }

    Install-Ffmpeg -Root $RepoRoot -BinDir $FfmpegBinDir

    $Icon = Join-Path $RepoRoot "assets\app_icon.ico"
    if (-not (Test-Path $Icon)) { throw "Missing icon: $Icon" }
    if (-not (Test-Path (Join-Path $RepoRoot "main.py"))) {
        throw "Missing entry point: main.py"
    }
    $EnvExample = Join-Path $RepoRoot ".env.example"
    if (Test-Path $EnvExample) {
        Write-Host "Bundling .env.example as runtime\env.example (API key is entered in the app)"
    }

    Write-Step "Freezing with PyInstaller (Fast standalone packaging)"
    $PyInstallerExe = Join-Path $RepoRoot "venv\Scripts\pyinstaller.exe"
    $DistDir = Join-Path $RepoRoot "sttmeet_dist_temp"
    $WorkDir = Join-Path $RepoRoot "build_pyi"

    if (Test-Path $DistDir) { Remove-Item -LiteralPath $DistDir -Recurse -Force }
    if (Test-Path $WorkDir) { Remove-Item -LiteralPath $WorkDir -Recurse -Force }

    $PyiArgs = @(
        "--onedir",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name=sttmeet",
        "--icon=$Icon",
        "--distpath=$RepoRoot",
        "--workpath=$WorkDir",
        "--contents-directory=_internal",
        "--collect-all=customtkinter",
        "--collect-all=google.genai",
        "--collect-all=docx",
        "--collect-all=pydub",
        "--add-data=.env.example;.",
        "--add-data=$RepoRoot\docs;docs",
        "main.py"
    )

    Write-Host "Running: pyinstaller $($PyiArgs -join ' ')"
    & $PyInstallerExe @PyiArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE."
    }

    # PyInstaller creates $RepoRoot\sttmeet. Rename/move to sttmeet.dist if needed
    $PyiOut = Join-Path $RepoRoot "sttmeet"
    $FinalDist = Join-Path $RepoRoot "sttmeet.dist"
    if (Test-Path $PyiOut) {
        if (Test-Path $FinalDist) {
            Remove-Item -LiteralPath $FinalDist -Recurse -Force -ErrorAction SilentlyContinue
        }
        $moved = $false
        for ($retry = 1; $retry -le 6; $retry++) {
            try {
                Move-Item -LiteralPath $PyiOut -Destination $FinalDist -Force -ErrorAction Stop
                $moved = $true
                break
            } catch {
                Start-Sleep -Milliseconds 1200
            }
        }
        if (-not $moved) {
            throw "Failed to move $PyiOut to ${FinalDist}: access denied or file locked by antivirus/indexer."
        }
    }
    Remove-Item -LiteralPath $WorkDir -Recurse -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path $ExeStandalone)) {
        throw "Build finished but sttmeet.exe was not found under sttmeet.dist\."
    }
    Write-Host "Freeze complete: $ExeStandalone"
} else {
    Write-Step "Installer only (-InstallerOnly) - skipping freeze"
}

if (-not $SkipInstaller) {
    $setupPath = Build-Installer -Root $RepoRoot -Version $AppVersion
    # Clean up intermediate PyInstaller dist folder once installer is generated
    $distDir = Join-Path $RepoRoot "sttmeet.dist"
    if ($setupPath -and (Test-Path $distDir)) {
        Write-Host "Cleaning up intermediate build folder sttmeet.dist\ ..."
        Remove-Item -LiteralPath $distDir -Recurse -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "Skipping installer (-SkipInstaller)"
    $setupPath = $null
}

Write-Step "Build complete"
if (Test-Path $ExeStandalone) {
    Write-Host "Standalone folder: $ExeStandalone"
}
if ($OneFile -and (Test-Path $ExeOneFile)) {
    Write-Host "One-file exe: $ExeOneFile"
}
if ($setupPath) {
    Write-Host "Installer: $setupPath" -ForegroundColor Green
    Write-Host "Primary deliverable: installer_output\sttmeet_setup.exe"
} else {
    Write-Warning "No installer was produced."
}

Write-Host ""
Write-Host "FFmpeg is bundled - end users do not need to install it."
Write-Host "App data (.env, cache, logs) lives in %LOCALAPPDATA%\STTMeet for installed builds."
Write-Host "Do not commit sttmeet.dist / sttmeet.build / vendor / installer_output (gitignored)."