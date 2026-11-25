"""A Claude Desktop extension (.mcpb) made for one person and this server.

It is a small local MCP server (stdio) that forwards each message to this server's /mcp over HTTPS. For a server
with its own certificate it trusts only that certificate, checked by its SHA-256 fingerprint. It signs in with an
OAuth refresh token minted for the person when they download it: that first token is short-lived and rotates on
first use (so a copy of the file is worth nothing once the extension has started, and reusing it revokes the
sign-in), and the extension keeps the rotated tokens in a file of its own under the person's home folder.
Claude Desktop ships its own Node, so nothing else needs installing.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import secrets
import uuid
import zipfile
from typing import Any

from sqlalchemy.orm import Session

from . import audit, claude_dist, config
from .db import OAuthClient, User
from .perms import Actor
from .security import issue_token

FIRST_TOKEN_HOURS = 24
NAME = "Claude Desktop"


def _icon_png() -> bytes | None:
    import os
    p = os.path.join(claude_dist.plugin_dir(), "icon.png")
    return open(p, "rb").read() if os.path.isfile(p) else None


def build(db: Session, actor: Actor, version: str = "1.0.0") -> tuple[bytes, str]:
    """The .mcpb bytes and its file name. Registers a client and mints the first (one-day) refresh token."""
    s = config.settings
    user: User = actor.user
    client = OAuthClient(client_id="abd_" + secrets.token_urlsafe(16), name=NAME, redirect_uris=[])
    db.add(client)
    db.flush()
    grant = uuid.uuid4().hex
    refresh, _ = issue_token(db, user, name=NAME, kind="oauth_refresh", client_id=client.client_id, grant_id=grant,
                             ttl=dt.timedelta(hours=FIRST_TOKEN_HOURS))
    audit.log(db, actor, "claude.desktop_extension", user.username)
    ca = claude_dist._ca()  # (pem, sha256) for a server with its own certificate
    conf = {"server": s.base_url, "client_id": client.client_id, "refresh_token": refresh,
            "ca_pem": ca[0].decode() if ca else None, "ca_sha256": ca[1] if ca else None}
    host = s.base_url.split("://", 1)[-1].split("/", 1)[0]
    manifest: dict[str, Any] = {
        "manifest_version": "0.3",
        "name": "artifact-buckets",
        "display_name": "Artifact Buckets",
        "version": version,
        "description": f"Save what Claude makes into your Artifact Buckets folders on {host}, and open files from them.",
        "author": {"name": "Artifact Buckets"},
        "homepage": "https://github.com/Seafinai/artifact-buckets",
        "server": {
            "type": "node",
            "entry_point": "server/index.js",
            "mcp_config": {"command": "node", "args": ["${__dirname}/server/index.js"], "env": {}},
        },
        "compatibility": {"platforms": ["darwin", "win32", "linux"], "runtimes": {"node": ">=18.0.0"}},
        "license": "Apache-2.0",
    }
    icon = _icon_png()
    if icon:
        manifest["icon"] = "icon.png"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("server/index.js", PROXY_JS)
        z.writestr("server/config.json", json.dumps(conf))
        if icon:
            z.writestr("icon.png", icon)
    return buf.getvalue(), "artifact-buckets.mcpb"


# The local server. Plain Node, no dependencies. Messages are newline-delimited JSON-RPC on stdin/stdout.
PROXY_JS = r"""'use strict';
// Artifact Buckets for Claude Desktop: forwards MCP messages from Claude to your Artifact Buckets server.
const fs = require('fs'), https = require('https'), http = require('http'), os = require('os'), path = require('path'),
  crypto = require('crypto'), readline = require('readline');

const conf = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8'));
const base = new URL(conf.server);
const stateDir = path.join(os.homedir(), '.artifact-buckets');
const stateFile = path.join(stateDir, 'desktop-' + base.host.replace(/[^A-Za-z0-9.-]/g, '_') + '.json');
const log = (m) => process.stderr.write('[artifact-buckets] ' + m + '\n');

function loadState() {
  try { const s = JSON.parse(fs.readFileSync(stateFile, 'utf8')); if (s.client_id === conf.client_id) return s; } catch (_) {}
  return { client_id: conf.client_id, refresh_token: conf.refresh_token };
}
function saveState(s) {
  fs.mkdirSync(stateDir, { recursive: true });
  const tmp = stateFile + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(s), { mode: 0o600 });
  fs.renameSync(tmp, stateFile);
}
let state = loadState(), access = null, sessionId = null, refreshing = null;

// Only this server's own certificate, matched by fingerprint, when it has one; the usual authorities otherwise.
const agentOpts = { keepAlive: true };
if (conf.ca_pem) {
  agentOpts.ca = conf.ca_pem;
  agentOpts.checkServerIdentity = (_host, cert) => {
    const fp = crypto.createHash('sha256').update(cert.raw).digest('hex').toUpperCase();
    return fp === conf.ca_sha256 ? undefined : new Error('The server showed a different certificate than expected');
  };
}
const lib = base.protocol === 'https:' ? https : http;
const agent = new lib.Agent(agentOpts);

function send(method, url, headers, body) {
  return new Promise((resolve, reject) => {
    const req = lib.request(url, { method, headers, agent, timeout: 120000 }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString('utf8') }));
    });
    req.on('timeout', () => req.destroy(new Error('timed out')));
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

async function refresh() {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const form = new URLSearchParams({ grant_type: 'refresh_token', refresh_token: state.refresh_token, client_id: state.client_id }).toString();
    const r = await send('POST', new URL('/oauth/token', base), { 'content-type': 'application/x-www-form-urlencoded', 'content-length': Buffer.byteLength(form) }, form);
    if (r.status !== 200) throw new Error('signed out (' + r.status + '): download the extension again from the Connect page');
    const t = JSON.parse(r.body);
    state = { client_id: state.client_id, refresh_token: t.refresh_token };
    saveState(state);
    access = t.access_token;
  })().finally(() => { refreshing = null; });
  return refreshing;
}

function parse(r) {
  const type = r.headers['content-type'] || '';
  if (!r.body.trim()) return [];
  if (type.includes('text/event-stream')) {
    return r.body.split(/\r?\n\r?\n/).map((ev) => ev.split(/\r?\n/).filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim()).join('\n'))
      .filter(Boolean).map((d) => JSON.parse(d));
  }
  const j = JSON.parse(r.body);
  return Array.isArray(j) ? j : [j];
}

async function forward(text, retried) {
  if (!access) await refresh();
  const headers = { 'content-type': 'application/json', accept: 'application/json, text/event-stream',
    authorization: 'Bearer ' + access, 'content-length': Buffer.byteLength(text) };
  if (sessionId) headers['mcp-session-id'] = sessionId;
  const r = await send('POST', new URL('/mcp', base), headers, text);
  if (r.status === 401 && !retried) { access = null; return forward(text, true); }
  if (r.headers['mcp-session-id']) sessionId = r.headers['mcp-session-id'];
  if (r.status === 202 || r.status === 204) return [];
  if (r.status >= 400) throw new Error('server answered ' + r.status);
  return parse(r);
}

function reply(m) { process.stdout.write(JSON.stringify(m) + '\n'); }

const rl = readline.createInterface({ input: process.stdin });
let chain = Promise.resolve();
rl.on('line', (line) => {
  if (!line.trim()) return;
  let msg; try { msg = JSON.parse(line); } catch (_) { return; }
  chain = chain.then(async () => {
    try { for (const out of await forward(line)) reply(out); }
    catch (e) {
      log(e.message);
      if (msg && msg.id !== undefined) reply({ jsonrpc: '2.0', id: msg.id, error: { code: -32000, message: 'Artifact Buckets: ' + e.message } });
    }
  });
});
rl.on('close', () => process.exit(0));
"""
