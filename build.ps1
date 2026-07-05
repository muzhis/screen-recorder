param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvName = "screen-recorder"
$Python = Join-Path $env:USERPROFILE ".conda\envs\$EnvName\python.exe"
$FfmpegPath = Join-Path $ProjectRoot "screen_recorder\resources\ffmpeg.exe"
$ResourceDir = Split-Path -Parent $FfmpegPath

Set-Location $ProjectRoot

if (-not (Test-Path $Python)) {
    throw "Python not found: $Python"
}

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue ".\build", ".\dist"
}

if (-not (Test-Path $FfmpegPath) -or ((Get-Item $FfmpegPath).Length -lt 1048576)) {
    $ffmpegCommand = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if (-not $ffmpegCommand) {
        throw "ffmpeg.exe not found. Put a real ffmpeg.exe at screen_recorder\resources\ffmpeg.exe first."
    }
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $ResourceDir "*.dll")
    Copy-Item -Force $ffmpegCommand.Source $FfmpegPath
    $ffmpegDir = Split-Path -Parent $ffmpegCommand.Source
    Get-ChildItem -Path $ffmpegDir -Filter "*.dll" -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item -Force $_.FullName (Join-Path $ResourceDir $_.Name)
    }
} elseif ((Get-Item $FfmpegPath).Length -gt 1048576) {
    $ffmpegDlls = Get-ChildItem -Path $ResourceDir -Filter "*.dll" -ErrorAction SilentlyContinue
    if ($ffmpegDlls.Count -gt 0) {
        Write-Host "Existing ffmpeg DLLs found. If your ffmpeg.exe is static, delete screen_recorder\resources\*.dll before building for a smaller package."
    }
}

& $Python -m pip install -r requirements.txt
& $Python -m pip install pyinstaller==6.11.1
& $Python -m PyInstaller --clean .\screen_recorder.spec

Write-Host ""
Write-Host "Build complete: dist\ScreenRecorder\ScreenRecorder.exe"
Write-Host "Distribute the whole folder: dist\ScreenRecorder"
