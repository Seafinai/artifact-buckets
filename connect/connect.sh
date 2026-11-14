#!/bin/sh
# Artifact Buckets: connect Claude Code to a server that uses its own (self-signed) certificate.
#
#   curl -fsSL https://raw.githubusercontent.com/Seafinai/artifact-buckets/main/connect/connect.sh | sh -s -- SERVER FINGERPRINT
#   curl -fsSL .../connect.sh | sh -s -- SERVER FINGERPRINT remove
#
# The Connect page in the web app shows the full line, with both values filled in. This script comes from
# GitHub over HTTPS, so nobody on the network can change it on the way. Before it trusts anything from the
# server, it checks that the server's certificate has the SHA-256 fingerprint from that line. Only then does
# it save the certificate and fetch the server's own setup (or removal) script, over HTTPS checked against
# that certificate, and run it. Nothing travels over plain HTTP.
#
# Licensed under the Apache License, Version 2.0.
set -eu

quit() { printf '\n  %s\n\n' "$1" >&2; exit 1; }
usage="Usage: connect.sh https://SERVER[:PORT] FINGERPRINT [remove]. Copy the full line from the Connect page."

SERVER=${1:-}
PIN=${2:-}
ACTION=${3:-setup}
[ -n "$SERVER" ] && [ -n "$PIN" ] || quit "$usage"
case $ACTION in setup|remove) ;; *) quit "$usage" ;; esac

# The server: https only, a host name or IPv4 address and an optional port, nothing else.
SERVER=${SERVER%/}
case $SERVER in https://*) ;; *) quit "The server address must start with https:// ($usage)" ;; esac
hostport=${SERVER#https://}
printf '%s' "$hostport" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?$' || quit "'$SERVER' isn't a server address this script can use."
case $hostport in *:*) host=${hostport%:*} port=${hostport##*:} ;; *) host=$hostport port=443 ;; esac

# The fingerprint: 64 hex digits; colons, spaces and lower case are fine.
PIN=$(printf '%s' "$PIN" | tr -d ': ' | tr 'a-f' 'A-F')
printf '%s' "$PIN" | grep -Eq '^[0-9A-F]{64}$' || quit "'$2' isn't a SHA-256 fingerprint (64 hex digits). Copy the full line from the Connect page."

command -v curl >/dev/null 2>&1 || quit "This needs curl. Install it, then run this again."
command -v openssl >/dev/null 2>&1 || quit "This needs openssl to check the server's certificate. Install it, then run this again."

tmp=$(mktemp -d 2>/dev/null || mktemp -d -t artifact-buckets)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 130' INT TERM

# 1. The certificate the server presents, compared with the fingerprint before anything else happens.
sni=""
printf '%s' "$host" | grep -Eq '^[0-9.]+$' || sni="-servername $host"
# shellcheck disable=SC2086
openssl s_client -connect "$host:$port" $sni </dev/null 2>/dev/null | openssl x509 -outform pem >"$tmp/server.crt" 2>/dev/null \
  || quit "Couldn't reach $SERVER. Check that the address opens in your browser, then run this again."
got=$(openssl x509 -in "$tmp/server.crt" -noout -fingerprint -sha256 2>/dev/null | sed 's/.*=//' | tr -d ':' | tr 'a-f' 'A-F')
if [ "$got" != "$PIN" ]; then
  quit "The server at $SERVER showed a different certificate from the one on the Connect page, so nothing was changed.
  Expected $PIN
  Got      ${got:-nothing}
  If the server's certificate was renewed, copy the line from the Connect page again. Otherwise tell your administrator:
  something on the network may be intercepting the connection."
fi

# 2. Keep the certificate (only this server's; nothing goes into the system trust store).
dir="$HOME/.artifact-buckets"
mkdir -p "$dir"
cp "$tmp/server.crt" "$dir/server.crt.new" && mv -f "$dir/server.crt.new" "$dir/server.crt"

# 3. The server's own script, over HTTPS that only that certificate can satisfy.
case $ACTION in setup) name=install.sh ;; remove) name=uninstall.sh ;; esac
curl -fsS --proto '=https' --cacert "$dir/server.crt" "$SERVER/claude/$name" -o "$tmp/$name" \
  || quit "Couldn't download the setup script from $SERVER over a checked connection. If you reach the server by an address
  its certificate doesn't name, use the address on the Connect page."
sh "$tmp/$name"
