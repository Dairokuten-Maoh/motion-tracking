param([string]$Model = 'small', [ValidateSet('cpu','cuda')][string]$Device = 'cpu')
Set-Location $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" receiver/transcribe.py --model $Model --device $Device
