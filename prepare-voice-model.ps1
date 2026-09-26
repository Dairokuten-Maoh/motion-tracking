$ErrorActionPreference = 'Stop'
$cache = Join-Path $PSScriptRoot '.tools/voice-model'
$archive = Join-Path $cache 'model.zip'
$target = Join-Path $PSScriptRoot 'android/app/src/main/assets/voice-model'
$expected = '30F26242C4EB449F948E42CB302DD7A686CB29A3423A8367F99FF41780942498'
New-Item -ItemType Directory -Force $cache | Out-Null
if (!(Test-Path $archive)) {
    Invoke-WebRequest 'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip' -OutFile $archive
}
if ((Get-FileHash $archive -Algorithm SHA256).Hash -ne $expected) { throw 'Voice model checksum mismatch.' }
if (!(Test-Path (Join-Path $target 'am/final.mdl'))) {
    Expand-Archive $archive -DestinationPath $cache -Force
    New-Item -ItemType Directory -Force $target | Out-Null
    Copy-Item (Join-Path $cache 'vosk-model-small-en-us-0.15/*') $target -Recurse -Force
}
