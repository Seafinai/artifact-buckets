# A public address for Claude's apps

Claude Code and the Claude desktop extension connect from each person's computer, so a server on your own network
is all they need. Claude's web, desktop and mobile apps reach connectors from Anthropic's servers on the internet
instead. For those, Artifact Buckets needs:

- a public `https://` address, such as `https://files.example.com`
- a certificate from a public authority (a self-signed one is refused)
- nothing in front of it that asks for a separate sign-in (Artifact Buckets does its own)

This is optional, and an admin sets it up once. Pick the way that fits how you already run things.

| You have | Use |
|---|---|
| A company domain and IT that runs a reverse proxy, load balancer or firewall publishing | [Your company's domain](#your-companys-domain) |
| A server the internet can reach on ports 80 and 443 | [A public name with Let's Encrypt](#a-public-name-with-lets-encrypt) |
| A small team and no IT | [Tailscale Funnel](#tailscale-funnel) or [Cloudflare Tunnel](#cloudflare-tunnel) |

After the switch, people add the connector in Claude: **Settings**, **Connectors**, **Add custom connector**, and the
address `https://<your public name>/mcp`. The Connect Claude page shows it once the address works.

## Your company's domain

For IT. Publish the server like any other internal web app:

1. **Name.** Create a DNS record, for example `files.example.com`, pointing at your reverse proxy, load balancer or
   published firewall rule.
2. **Certificate.** Use your usual public certificate for that name (wildcard or per-host) on the proxy.
3. **Route.** Send `https://files.example.com/*` to the server's HTTPS port (443, or the port in
   `/opt/artifact-buckets/.env`). If the proxy checks the server's certificate, trust the one in
   `/opt/artifact-buckets/data/tls/public/server.crt`, or send to the HTTP port instead on a trusted network.
   Keep the `Host` header, allow request bodies up to 500 MB, and don't buffer or time out streamed responses on
   `/mcp` under 120 seconds.
4. **No extra sign-in on the API paths.** If your proxy adds single sign-on, leave out `/mcp`, `/oauth`,
   `/.well-known` and `/claude`: Claude's servers can't pass it, and Artifact Buckets checks every request itself.
5. **Tell the app its address.** On the server: `sudo sed -i 's|^AB_BASE_URL=.*|AB_BASE_URL=https://files.example.com|' /opt/artifact-buckets/.env`, then
   `sudo artifact-buckets restart`.

## A public name with Let's Encrypt

On a machine the internet reaches on ports 80 and 443, install (or install again) with
`--host files.example.com --tls letsencrypt`. Caddy gets and renews the certificate by itself.

## Tailscale Funnel

[Tailscale Funnel](https://tailscale.com/kb/1223/funnel) gives the server a public `https://<machine>.<tailnet>.ts.net`
address with a trusted certificate, with no ports to open. You need a free Tailscale account with Funnel allowed
for the machine.

1. On the server: install Tailscale and sign in (`curl -fsSL https://tailscale.com/install.sh | sh`, then
   `sudo tailscale up`).
2. Publish the app: `sudo tailscale funnel --bg https+insecure://localhost:443` (use the HTTPS port from
   `/opt/artifact-buckets/.env` if it isn't 443). It prints the public address.
3. Tell the app that address, as in step 5 above, and restart.

## Cloudflare Tunnel

A [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)
works the same way and is built into the installer. You need a domain whose DNS is on Cloudflare.

### 1. Create the tunnel in Cloudflare

1. In the [Cloudflare dashboard](https://dash.cloudflare.com/), open **Zero Trust**, then **Networks**, then
   **Tunnels**, and choose **Create a tunnel**.
2. Pick **Cloudflared** as the connector type and name the tunnel, for example `artifact-buckets`.
3. On the install step, choose **Docker**. Copy the long token that follows `--token` in the command it shows.
   Don't run that command: the installer runs the connector for you.
4. Add a public hostname (Cloudflare may call it a *published application route*):
   - **Subdomain** and **Domain**: the address people will use, for example `files` and `example.com`
   - **Service type**: `HTTP`
   - **URL**: `app:8080`
5. Save the tunnel.

`app:8080` is the Artifact Buckets container on its own Docker network, which the connector joins. Nothing on
the host listens for it, so the tunnel can reach the app and nothing else.

### 2. Connect the server

On the server:

```bash
sudo artifact-buckets tunnel --host files.example.com
```

Paste the token when it asks (it isn't shown as you paste). The command:

- stores the token in `/opt/artifact-buckets/tunnel.env`, readable only by root and given only to the connector
- starts the `cloudflared` container next to the app
- makes `https://files.example.com` the app's address, for sign-in, links and the Claude Code setup lines
- waits until the public address answers

For scripts, pass the token instead: `--token <token>`. It then shows up in the process list and your shell
history, so prefer the prompt.

Within a minute the tunnel shows **Healthy** in Cloudflare, and **Connect Claude** in the app shows the steps for
Claude's apps instead of a warning.

### 3. Add the connector in Claude

In Claude (web or desktop), open **Settings**, then **Connectors**, and choose **Add custom connector**. Name it
*Artifact Buckets* and paste `https://files.example.com/mcp`. Press **Connect**, sign in to Artifact Buckets if
asked, and press **Connect** on the page it opens. The connection then shows under **Connect Claude**, where
either side can disconnect it.

On a Team or Enterprise plan, an owner adds the connector once under **Organization settings**, then
**Connectors**. Each person then connects with their own Artifact Buckets account, and sees only the folders they
can see in the web app.

### Things to know

- **Computers already running Claude Code** keep working only while the old address answers. After the switch,
  run the new setup line from **Connect Claude** on each of them (or push the new managed settings), so they sign
  in at the public address.
- **The local address still works** in a browser on your network.
- **Upload size.** Cloudflare's free and Pro plans accept requests up to 100 MB, so a single save through the
  tunnel is capped there, even though Artifact Buckets allows 500 MB. Saves from Claude Code on your network to the
  local address aren't affected.
- **Don't put Cloudflare Access in front of it.** Claude's servers can't pass an Access login, so the connector
  would fail. Artifact Buckets already requires a sign-in for every file and every tool. If you want Access for people's browsers, apply it to `/` only and leave out `/mcp`, `/oauth`,
  `/.well-known` and `/claude`.
- **Turning it off:** `sudo artifact-buckets tunnel --off` stops the connector and puts the old address back.
  Delete the tunnel in Cloudflare afterwards.
- **Upgrades and reinstalls** keep the tunnel. An uninstall removes the token; run `tunnel` again after
  installing again.

## Sending files, not only text

Claude can already save anything it writes as text (documents, code, CSV, HTML) through the connector. Claude
also has a beta feature that sends real files, such as an attached PDF or a generated slide deck, straight to a
connected app. Artifact Buckets supports the open protocol behind it (the MCP files extension: a `save_file` and
a `download_file` tool), but Claude only uses that feature with apps listed in its connectors directory, so for
now a self-hosted server receives files as text through the connector. See [claude-apps.md](claude-apps.md).
