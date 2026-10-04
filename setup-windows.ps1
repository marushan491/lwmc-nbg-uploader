$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  Write-Host 'Bitte FFmpeg installieren: winget install --id Gyan.FFmpeg -e'
  Write-Host 'Danach neues Terminal öffnen und Einrichtung wiederholen.'
  exit 1
}
py -3 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ fehlt. Von python.org installieren.' }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Abhängigkeiten konnten nicht installiert werden.' }
if (-not (Test-Path config.json)) { Copy-Item config.example.json config.json }
Write-Host 'Fertig. Anwendung mit start-windows.bat öffnen.'
