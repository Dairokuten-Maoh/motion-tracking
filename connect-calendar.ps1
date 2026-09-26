Set-Location $PSScriptRoot
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\.venv\Scripts\python.exe" receiver/connect_calendar.py
if ($LASTEXITCODE -ne 0) { throw 'Calendar connection did not complete. See google-calendar-setup.md.' }
