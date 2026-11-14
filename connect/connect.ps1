# Artifact Buckets: connect Claude Code to a server that uses its own (self-signed) certificate.
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Seafinai/artifact-buckets/main/connect/connect.ps1))) SERVER FINGERPRINT
#   & ([scriptblock]::Create((irm .../connect.ps1))) SERVER FINGERPRINT remove
#
# The Connect page in the web app shows the full line, with both values filled in. This script comes from
# GitHub over HTTPS, so nobody on the network can change it on the way. Before it trusts anything from the
# server, it checks that the server's certificate has the SHA-256 fingerprint from that line. Only then does
# it save the certificate and fetch the server's own setup (or removal) script over a connection checked
# against that certificate, and run it. Nothing travels over plain HTTP, and nothing is added to the Windows
# certificate store. Works in Windows PowerShell 5.1 and PowerShell 7.
#
# Licensed under the Apache License, Version 2.0.
param([string]$Server, [string]$Fingerprint, [string]$Action = 'setup')

function Stop-Connect($m) { Write-Host ""; Write-Host "  $m" -ForegroundColor Yellow; Write-Host "" }
$usage = "Copy the full line from the Connect page: it ends with the server's address and its certificate fingerprint."

if (-not $Server -or -not $Fingerprint -or @('setup', 'remove') -notcontains $Action) { Stop-Connect $usage; return }
$Server = $Server.TrimEnd('/')
if ($Server -notmatch '^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?$') {
  Stop-Connect "'$Server' isn't a server address this script can use (it must start with https://). $usage"; return
}
$AbPin = ($Fingerprint -replace '[:\s]', '').ToUpperInvariant()
if ($AbPin -notmatch '^[0-9A-F]{64}$') { Stop-Connect "'$Fingerprint' isn't a SHA-256 fingerprint (64 hex digits). $usage"; return }

# One HTTPS request whose certificate must be exactly the pinned one. The certificate is compared right after
# the TLS handshake, before a single byte of the request is sent; the system trust store plays no part.
# The server's setup script uses this too (it runs in this scope), so it never needs plain HTTP either.
function Get-AbHttps([string]$Url, [string]$Pin = $AbPin) {
  $u = [Uri]$Url
  if ($u.Scheme -ne 'https') { throw "Not an https address: $Url" }
  $tcp = New-Object System.Net.Sockets.TcpClient
  try {
    $tcp.ReceiveTimeout = 60000; $tcp.SendTimeout = 60000
    $tcp.Connect($u.DnsSafeHost, $u.Port)
    $accept = [System.Net.Security.RemoteCertificateValidationCallback] { $true }   # judged below, by fingerprint only
    $ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false, $accept)
    $ssl.AuthenticateAsClient($u.DnsSafeHost, $null, [System.Security.Authentication.SslProtocols]::Tls12, $false)
    $raw = $ssl.RemoteCertificate.GetRawCertData()
    $got = [BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash($raw)).Replace('-', '')
    if ($got -ne $Pin) { throw [System.Security.Authentication.AuthenticationException] "The server's certificate ($got) isn't the expected one ($Pin)." }
    $req = [Text.Encoding]::ASCII.GetBytes("GET $($u.PathAndQuery) HTTP/1.0`r`nHost: $($u.Authority)`r`nUser-Agent: artifact-buckets-connect`r`nAccept-Encoding: identity`r`nConnection: close`r`n`r`n")
    $ssl.Write($req, 0, $req.Length); $ssl.Flush()
    $ms = New-Object System.IO.MemoryStream
    try { $ssl.CopyTo($ms) } catch [System.IO.IOException] { if ($ms.Length -eq 0) { throw } }   # a close without TLS close_notify
    $all = $ms.ToArray()
    $end = -1
    for ($i = 0; $i -le $all.Length - 4; $i++) { if ($all[$i] -eq 13 -and $all[$i + 1] -eq 10 -and $all[$i + 2] -eq 13 -and $all[$i + 3] -eq 10) { $end = $i; break } }
    if ($end -lt 0) { throw "No reply from $Url" }
    $head = [Text.Encoding]::ASCII.GetString($all, 0, $end)
    if ($head -notmatch '^HTTP/1\.[01] 200 ') { throw "$Url answered: $(($head -split "`r`n")[0])" }
    $body = New-Object byte[] ($all.Length - $end - 4)
    [Array]::Copy($all, $end + 4, $body, 0, $body.Length)
    if ($head -match '(?im)^Content-Length:\s*(\d+)\s*$' -and [int64]$Matches[1] -ne $body.Length) { throw "The download from $Url was cut short." }
    if ($head -match '(?im)^Transfer-Encoding:') { throw "Unexpected reply from $Url" }
    return ,$body
  } finally { $tcp.Close() }
}

Write-Host ""
Write-Host "  Checking the server's certificate" -ForegroundColor DarkGray
try {
  $u = [Uri]$Server
  $tcp = New-Object System.Net.Sockets.TcpClient
  try {
    $tcp.Connect($u.DnsSafeHost, $u.Port)
    $ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false, ([System.Net.Security.RemoteCertificateValidationCallback] { $true }))
    $ssl.AuthenticateAsClient($u.DnsSafeHost, $null, [System.Security.Authentication.SslProtocols]::Tls12, $false)
    $raw = $ssl.RemoteCertificate.GetRawCertData()
  } finally { $tcp.Close() }
} catch { Stop-Connect "Couldn't reach $Server ($($_.Exception.Message)). Check that the address opens in your browser, then run this again."; return }
$got = [BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash($raw)).Replace('-', '')
if ($got -ne $AbPin) {
  Stop-Connect ("The server at $Server showed a different certificate from the one on the Connect page, so nothing was changed.`n" +
    "  Expected $AbPin`n  Got      $got`n" +
    "  If the server's certificate was renewed, copy the line from the Connect page again. Otherwise tell your administrator:`n" +
    "  something on the network may be intercepting the connection.")
  return
}

# Keep the certificate (for Claude Code and the sync script; only this server's, and not in the Windows store).
$dir = Join-Path $HOME '.artifact-buckets'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$b64 = [Convert]::ToBase64String($raw)
$pem = "-----BEGIN CERTIFICATE-----`n" + (($b64 -split '(.{64})' | Where-Object { $_ }) -join "`n") + "`n-----END CERTIFICATE-----`n"
[IO.File]::WriteAllText((Join-Path $dir 'server.crt'), $pem)

$name = if ($Action -eq 'remove') { 'uninstall.ps1' } else { 'install.ps1' }
try { $script = [Text.Encoding]::UTF8.GetString((Get-AbHttps "$Server/claude/$name")) }
catch { Stop-Connect "Couldn't download the setup script from $Server ($($_.Exception.Message))."; return }
if ($script.Length -gt 0 -and $script[0] -eq [char]0xFEFF) { $script = $script.Substring(1) }
& ([scriptblock]::Create($script))
