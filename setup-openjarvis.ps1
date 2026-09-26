$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$revision = '309a4f1044ccfb2032264832a31fef2f1d314586'
$checkout = Join-Path $PSScriptRoot '.tools/openjarvis-review'
$uvPath = Join-Path $env:USERPROFILE '.local/bin/uv.exe'
if (!(Test-Path -LiteralPath $uvPath)) { $uvPath = (Get-Command uv -ErrorAction Stop).Source }
if (!(Test-Path -LiteralPath $checkout)) {
    $ErrorActionPreference = 'Continue'
    git clone https://github.com/open-jarvis/OpenJarvis.git $checkout
    $cloneCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($cloneCode -ne 0) { throw 'OpenJarvis clone failed' }
    git -C $checkout checkout --detach $revision
    if ($LASTEXITCODE -ne 0) { throw 'Cannot select pinned OpenJarvis revision' }
}
$actual = git -C $checkout rev-parse HEAD
if ($actual -ne $revision) { throw 'Existing OpenJarvis checkout differs from the reviewed revision' }
if (git -C $checkout status --porcelain) { throw 'OpenJarvis checkout has local changes; review them before installation' }
$runtimePython = Join-Path $PSScriptRoot '.tools/openjarvis-env/Scripts/python.exe'
$ErrorActionPreference = 'Continue'
if (!(Test-Path -LiteralPath $runtimePython)) {
    & $uvPath venv '.tools/openjarvis-env' --python '.venv/Scripts/python.exe'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create isolated OpenJarvis environment' }
}
& $uvPath pip install --system-certs --python $runtimePython -r receiver/requirements-openjarvis.txt
if ($LASTEXITCODE -ne 0) { throw 'OpenJarvis dependency installation failed' }
& $runtimePython receiver/openjarvis_worker_checks.py
if ($LASTEXITCODE -ne 0) { throw 'OpenJarvis worker checks failed' }
$ErrorActionPreference = 'Stop'
Write-Output 'OpenJarvis candidate prepared. The active backend has not been changed.'
