# Expose the local receiver only inside the signed-in Tailscale network.
# Run after signing in on both PC and phone; no router forwarding is needed.
$ErrorActionPreference = 'Stop'
$tailscale = Join-Path $env:ProgramFiles 'Tailscale/tailscale.exe'
if (!(Test-Path $tailscale)) { throw 'Install Tailscale on this PC first.' }
$state = & $tailscale status --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $state.BackendState -ne 'Running') {
    throw 'Sign in to Tailscale on this PC, then run this script again.'
}
$dnsName = $state.Self.DNSName.TrimEnd('.')
if (!$dnsName) { throw 'Tailscale has not assigned this PC a DNS name yet.' }
$tokenPath = Join-Path $PSScriptRoot 'jarvis-data/token.txt'
$headers = @{ Authorization = 'Bearer ' + (Get-Content -LiteralPath $tokenPath -Raw).Trim() }
$health = Invoke-RestMethod 'http://127.0.0.1:8765/health' -Headers $headers -TimeoutSec 10
if ($health.status -ne 'ready') { throw 'Start the Jarvis receiver before enabling remote access.' }
$existing = & $tailscale serve status --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Cannot read the current Tailscale Serve configuration.' }
if ($existing.TCP -or $existing.Web -or $existing.AllowFunnel) {
    throw 'Tailscale already has a Serve configuration. Review it before changing any routes.'
}
& $tailscale serve --bg --https=443 http://127.0.0.1:8765
if ($LASTEXITCODE -ne 0) { throw 'Tailscale Serve setup did not complete. Follow any HTTPS enablement link it printed, then retry.' }
$endpoint = "https://$dnsName"
@{ endpoint = $endpoint; transport = 'tailscale-serve' } | ConvertTo-Json | Set-Content (Join-Path $PSScriptRoot 'jarvis-data/remote.json')
try {
    $health = Invoke-RestMethod "$endpoint/health" -Headers $headers -TimeoutSec 20
    if ($health.status -ne 'ready') { throw 'Unexpected health response.' }
    Write-Output "Verified Jarvis endpoint from PC: $endpoint"
} catch {
    # A self-connection can fail even when a peer can reach Serve. Keep the
    # configured route and require a peer check rather than claiming failure or success.
    Write-Warning "Route configured, but the PC self-check failed. Verify HTTPS from the phone before using it: $endpoint"
}
Write-Output 'In Jarvis on the phone, stop listening, replace Receiver URL with this endpoint, keep the pairing token, and start listening again.'
