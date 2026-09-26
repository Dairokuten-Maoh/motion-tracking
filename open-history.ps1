Set-Location $PSScriptRoot
if (!(Test-Path 'jarvis-data/token.txt')) { throw 'Start the receiver first.' }
Set-Clipboard -Value (Get-Content 'jarvis-data/token.txt' -Raw).Trim()
Start-Process 'http://127.0.0.1:8765/'
Write-Host 'Pairing token copied. Paste it into the history page to unlock.'
