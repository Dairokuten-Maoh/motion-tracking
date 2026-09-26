Set-Location $PSScriptRoot
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\prepare-voice-model.ps1"
$localJdk = Get-ChildItem "$PSScriptRoot\.tools\jdk17" -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
if ($localJdk) { $env:JAVA_HOME = $localJdk.FullName }
if (!$env:JAVA_HOME) { throw 'Set JAVA_HOME to a JDK 17 installation, or select JDK 17 in Android Studio.' }
$env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$env:JAVA_OPTS = "$env:JAVA_OPTS -Djavax.net.ssl.trustStoreType=Windows-ROOT -Djavax.net.ssl.trustStore=NUL"
$gradlePath = "$PSScriptRoot\android\gradlew.bat"
if (Test-Path "$PSScriptRoot\.tools\gradle-8.9\bin\gradle.bat") { $gradlePath = "$PSScriptRoot\.tools\gradle-8.9\bin\gradle.bat" }
# Windows PowerShell treats javac notes on stderr as errors when redirected.
# Gradle's exit code, rather than the output stream, determines build success.
$ErrorActionPreference = 'Continue'
& $gradlePath -p "$PSScriptRoot\android" '-Djavax.net.ssl.trustStoreType=Windows-ROOT' '-Djavax.net.ssl.trustStore=NUL' assembleDebug lintDebug testDebugUnitTest --console=plain
$ErrorActionPreference = 'Stop'
if ($LASTEXITCODE -ne 0) { throw 'Android build failed.' }
