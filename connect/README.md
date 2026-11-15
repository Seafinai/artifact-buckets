# Connect Claude Code to an Artifact Buckets server

These steps are written for Claude Code, run on the person's own computer. The person gave you two values from
the Connect page of their Artifact Buckets server: the **server address** (it starts with `https://`) and the
server certificate's **SHA-256 fingerprint** (64 hex digits). If either is missing, ask them to copy the prompt
from the Connect page again; don't guess.

The server uses its own (self-signed) certificate. The connect script in this folder checks that certificate
against the fingerprint before it trusts anything from the server, then fetches and runs the server's own setup
script over that checked connection. So nothing travels over plain HTTP, and nothing is added to the system's
or the browser's trust store.

Keep it light for the person: say in a sentence or two what you're about to do, then do it. Every step is safe
to repeat. The person makes one choice, on one page in their browser; don't ask them questions in the terminal
that the page already asks. If they told you up front to keep some folders out (a client's work, say), remind
them to untick those on that page.

## Set up

1. Download the connect script for this computer from the same folder as this page, and read it (it's short):
   - Windows: `connect.ps1`
   - macOS and Linux: `connect.sh`

   Save it somewhere outside `~/.artifact-buckets` (a temporary folder is fine).
2. Run it with the server address and the fingerprint, with a ten-minute timeout (the person presses Connect in
   the browser while it waits):
   - Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File <path to connect.ps1> <server> <fingerprint>`
   - macOS and Linux: `sh <path to connect.sh> <server> <fingerprint>`
3. If it says the certificate didn't match, **stop**. Tell the person exactly what it printed. Either the server's
   certificate was renewed (they copy the prompt from the Connect page again) or something on the network is
   intercepting the connection (they tell their administrator). Don't work around it.
4. Otherwise it installs the plugin, opens one page in the browser, and signs Claude Code in. Tell the person what
   the page shows: the folders of Claude's existing work that would be copied, each with a tick box. They untick
   anything that shouldn't leave this computer and press **Connect and copy**, or **Connect without syncing**.
5. Confirm `claude mcp list` shows `plugin:artifact-buckets:artifact-buckets` as Connected, and tell the person
   what happened (the script prints it). A new Claude Code window (or `/reload-plugins` in this one) picks up the
   plugin. Something to try: "save this to my buckets".

If scripts can't run here at all, the server explains every step for doing it by hand at `<server>/claude/setup.md`.
Fetch it only over a connection checked against the fingerprint: first save the server's certificate and confirm
its SHA-256 fingerprint (`openssl s_client -connect <host>:<port> </dev/null | openssl x509 > server.crt`, then
`openssl x509 -in server.crt -noout -fingerprint -sha256`), then `curl --cacert server.crt <server>/claude/setup.md`.

## Remove

Only when the person asks. Files already on the server stay there. Run the same script with `remove` after the
fingerprint, the same way as setup:

- Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File <path to connect.ps1> <server> <fingerprint> remove`
- macOS and Linux: `sh <path to connect.sh> <server> <fingerprint> remove`

Then check: `claude plugin list` no longer shows `artifact-buckets`, `~/.artifact-buckets` is gone, and
`NODE_EXTRA_CA_CERTS` no longer points into it. Tell the person to close open Claude Code windows.

## For administrators

A server with a public certificate (Let's Encrypt, or your own CA) doesn't need this folder: its Connect page
shows lines that fetch setup straight from the server. If computers can't reach GitHub, host `connect.sh`,
`connect.ps1` and this page on any HTTPS address they trust and set `AB_CONNECT_URL` to that folder's address.
