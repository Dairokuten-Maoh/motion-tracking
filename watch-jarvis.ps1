param([switch]$Once)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$data = Join-Path $PSScriptRoot 'jarvis-data'
$logs = Join-Path $data 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
# One supervisor per workspace; a manual invocation cannot duplicate the scheduled one.
$hash = [System.Security.Cryptography.SHA256]::Create()
$identity = [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($PSScriptRoot.ToLowerInvariant()))).Replace('-','').Substring(0,16)
$hash.Dispose()
$mutex = New-Object System.Threading.Mutex($false, "Local\Jarvis-$identity")
$acquired = $false
$lastLaunch = @{}

function Write-Event([string]$Message) {
    $file = Join-Path $logs 'watchdog.log'
    if ((Test-Path $file) -and (Get-Item $file).Length -gt 2MB) {
        Move-Item -LiteralPath $file -Destination "$file.previous" -Force
    }
    Add-Content -LiteralPath $file -Value "$(Get-Date -Format o) $Message"
}

# Identify only this workspace's venv launchers, including the original relative commands.
# The base-Python child of the Windows venv launcher is deliberately not a second worker.
function Find-Worker([string]$Script) {
    $relative = [regex]::Escape("receiver/$Script")
    $absolute = [regex]::Escape((Join-Path $PSScriptRoot "receiver/$Script").Replace('\','/'))
    $pattern = '(?:^|\s|")(?:{0}|{1})(?:"|\s|$)' -f $relative, $absolute
    @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
        $_.ExecutablePath -eq $python -and
        $_.CommandLine.Replace('\','/') -match $pattern
    })
}

function Start-Logged([string]$Name, [string]$Executable, [string]$Arguments) {
    if ($lastLaunch.ContainsKey($Name) -and ((Get-Date) - $lastLaunch[$Name]).TotalSeconds -lt 60) { return }
    $lastLaunch[$Name] = Get-Date
    foreach ($suffix in @('out','err')) {
        $file = Join-Path $logs "$Name.$suffix.log"
        if (Test-Path $file) { Move-Item -LiteralPath $file -Destination "$file.previous" -Force }
    }
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs "$Name.out.log") -RedirectStandardError (Join-Path $logs "$Name.err.log")
    Write-Event "Started $Name PID $($process.Id)"
    return $process.Id
}

try {
    try { $acquired = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $acquired = $true }
    if (!$acquired) { Write-Output 'Jarvis watchdog is already running.'; return }
    Write-Event 'Watchdog started'
    do {
        try {
            $pids = [ordered]@{ WatchdogPID = $PID }
            $workers = [ordered]@{ ReceiverPID='server.py'; TranscriptionPID='transcribe.py'; DiaryPID='diary.py' }
            if (Test-Path (Join-Path $data 'aws.json')) { $workers.CloudArchivePID = 's3_archive.py' }
            foreach ($key in $workers.Keys) {
                $script = $workers[$key]
                $found = @(Find-Worker $script)
                if ($found.Count -gt 1) { Write-Event "Multiple $script launchers detected; leaving them unchanged" }
                if ($found.Count) { $pids[$key] = $found[0].ProcessId }
                else { $pids[$key] = Start-Logged $script $python "-u `"$(Join-Path $PSScriptRoot "receiver/$script")`"" }
            }
            # Reuse the desktop Ollama server. Never kill it or start a second server on its port.
            try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 }
            catch {
                $ollama = Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe'
                $existing = @(Get-CimInstance Win32_Process -Filter "Name='ollama.exe'" | Where-Object { $_.CommandLine -match '\bserve\b' })
                if (!$existing.Count -and (Test-Path $ollama)) { $null = Start-Logged 'ollama' $ollama 'serve' }
            }
            $pids | ConvertTo-Json | Set-Content (Join-Path $data 'processes.json.tmp')
            Move-Item -LiteralPath (Join-Path $data 'processes.json.tmp') -Destination (Join-Path $data 'processes.json') -Force
        } catch { Write-Event "Supervisor check failed: $($_.Exception.Message)" }
        if (!$Once) { Start-Sleep -Seconds 15 }
    } while (!$Once)
} finally {
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
