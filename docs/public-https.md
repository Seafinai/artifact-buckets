# A public address with Cloudflare Tunnel

Claude Code connects from each person's computer, so a server on your own network is enough for it. Claude's
web, desktop and mobile apps are different: they reach connectors from Anthropic's servers on the internet. For
them, Artifact Buckets needs:

- a public `https://` address, such as `https://files.example.com`
- a certificate from a public authority (a self-signed one is refused)
- nothing in front of it that asks for a separate sign-in (Artifact Buckets does its own)

A [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)
gives you all three without opening a port or touching your firewall. A small `cloudflared` container makes an
outbound connection to Cloudflare, and Cloudflare serves your public name with its own certificate. It's free,
and takes about ten minutes.

You need a domain whose DNS is on Cloudflare, and an Artifact Buckets server installed with `install.sh`.

## 1. Create the tunnel in Cloudflare

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

## 2. Connect the server

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

## 3. Add the connector in Claude

In Claude (web or desktop), open **Settings**, then **Connectors**, and choose **Add custom connector**. Name it
*Artifact Buckets* and paste `https://files.example.com/mcp`. Press **Connect**, sign in to Artifact Buckets if
asked, and press **Connect** on the page it opens. The connection then shows under **Connect Claude**, where
either side can disconnect it.

On a Team or Enterprise plan, an owner adds the connector once under **Organization settings**, then
**Connectors**. Each person then connects with their own Artifact Buckets account, and sees only the folders they
can see in the web app.

## Things to know

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

## Other ways to get a public address

Any of these work instead of a tunnel, as long as the address is public `https` with a trusted certificate:

- **A public name pointing at the server.** Install with `--host files.example.com --tls letsencrypt` on a machine
  that the internet reaches on ports 80 and 443. Caddy gets a Let's Encrypt certificate by itself.
- **Your own reverse proxy or load balancer** with a public certificate, sending traffic to the server's HTTPS
  port. Set the app's address to the public one (`AB_BASE_URL` in `/opt/artifact-buckets/.env`) and restart.

## Sending files, not only text

Claude can already save anything it writes as text (documents, code, CSV, HTML) through the connector. Claude
also has a beta feature that sends real files, such as an attached PDF or a generated slide deck, straight to a
connected app. Artifact Buckets supports the open protocol behind it (the MCP files extension: a `save_file` and
a `download_file` tool), but Claude only uses that feature with apps listed in its connectors directory, so for
now a self-hosted server receives files as text through the connector. See [claude-apps.md](claude-apps.md).
