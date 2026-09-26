Set-Location $PSScriptRoot
$adbPath = Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'
if (!(Test-Path $adbPath)) { throw 'Install Android SDK platform-tools first.' }
& $adbPath devices
& $adbPath reverse tcp:8765 tcp:8765
if ($LASTEXITCODE -ne 0) { throw 'Connect the phone over USB and accept its USB debugging prompt.' }
& $adbPath install -r "$PSScriptRoot\android\app\build\outputs\apk\debug\app-debug.apk"
if ($LASTEXITCODE -ne 0) { throw 'APK install failed.' }
& $adbPath shell am start -n local.jarvis.capture/.MainActivity
