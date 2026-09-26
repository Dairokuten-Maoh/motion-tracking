param([string]$BindAddress = '127.0.0.1')
Set-Location $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" receiver/server.py --host $BindAddress
