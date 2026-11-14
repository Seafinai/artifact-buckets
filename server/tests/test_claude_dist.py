"""The server hands out its own Claude Code plugin, installers and IT policy, with its address built in."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

from fastapi.testclient import TestClient


def _client(env, monkeypatch, **extra):
    for k, v in extra.items():
        monkeypatch.setenv(k, v)
    from app import config
    config.reload_settings()
    from app.main import create_app
    c = TestClient(create_app())
    c.__enter__()  # runs startup: tables, first admin
    return c


def test_marketplace_and_zip_carry_this_servers_address(env, monkeypatch):
    c = _client(env, monkeypatch)
    m = c.get("/claude/marketplace.json").json()
    assert m["name"] == "artifact-buckets"
    p = m["plugins"][0]
    assert p["name"] == "artifact-buckets" and p["source"]["source"] == "archive"
    url = p["source"]["url"]
    assert url.startswith("http://testserver/claude/artifact-buckets-") and url.endswith(".zip")
    r = c.get(url.replace("http://testserver", ""))
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert hashlib.sha256(r.content).hexdigest() == p["source"]["sha256"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert ".claude-plugin/plugin.json" in names and "commands/buckets-open.md" in names
    mcp = json.loads(z.read(".mcp.json"))
    assert mcp == {"mcpServers": {"artifact-buckets": {"type": "http", "url": "http://testserver/mcp"}}}
    # Same plugin and address give the same bytes, so Claude Code sees no fake update.
    assert c.get("/claude/marketplace.json").json() == m
    assert c.get("/claude/artifact-buckets-0.0.0.zip").status_code == 404


def test_installers_and_policy(env, monkeypatch):
    c = _client(env, monkeypatch, AB_INSTALL_URL="http://boot.example:8090")
    me = c.get("/api/auth/me").json()["claude"]
    assert me["windows"] == "irm http://boot.example:8090/claude/install.ps1 | iex"
    assert me["unix"] == "curl -fsSL http://boot.example:8090/claude/install.sh | sh"
    assert me["private_ca"] is False
    pol = c.get("/claude/managed-settings.json").json()
    assert pol["enabledPlugins"] == {"artifact-buckets@artifact-buckets": True}
    assert pol["extraKnownMarketplaces"]["artifact-buckets"]["source"] == {"source": "url", "url": "http://testserver/claude/marketplace.json"}
    for path in ("/claude/install.ps1", "/claude/install.sh"):
        s = c.get(path).text
        assert "{{" not in s and "http://testserver/claude/marketplace.json" in s
        assert "plugin:artifact-buckets:artifact-buckets" in s
        assert "CaSha = ''" in s or "CA_SHA=''" in s
    assert c.get("/claude/ca.crt").status_code == 404
    # Not swallowed by the web app's page fallback.
    assert c.get("/claude/nope").status_code == 404


def _private_ca(env, monkeypatch, tmp_path, **extra):
    import base64
    der = b"\x30\x03\x02\x01\x01"  # any bytes: only the fingerprint matters here
    pem = b"-----BEGIN CERTIFICATE-----\n" + base64.b64encode(der) + b"\n-----END CERTIFICATE-----\n"
    f = tmp_path / "server.crt"
    f.write_bytes(pem)
    c = _client(env, monkeypatch, AB_INSTALL_CA_FILE=str(f), AB_BASE_URL="https://files.example.lan:8443", **extra)
    return c, pem, hashlib.sha256(der).hexdigest().upper()


def test_private_ca_is_pinned_in_installers(env, monkeypatch, tmp_path):
    c, pem, sha = _private_ca(env, monkeypatch, tmp_path, AB_INSTALL_URL="http://boot.example:8090")
    https = TestClient(c.app, base_url="https://testserver")
    assert c.get("/claude/ca.crt").content == pem  # harmless over http: the fingerprint is what's checked
    ps1 = https.get("/claude/install.ps1").text
    assert f"$CaSha = '{sha}'" in ps1 and "Get-AbHttps" in ps1
    assert "http://" not in ps1.replace("http://localhost", "")  # nothing from setup over plain http
    sh = https.get("/claude/install.sh").text
    assert f"CA_SHA='{sha}'" in sh and "CA_URL" not in sh and "http://boot.example" not in sh
    me = c.get("/api/auth/me").json()["claude"]
    assert me["private_ca"] is True and me["fingerprint"] == sha


def test_private_ca_setup_lines_come_from_github_and_carry_the_fingerprint(env, monkeypatch, tmp_path):
    c, _, sha = _private_ca(env, monkeypatch, tmp_path, AB_INSTALL_URL="http://boot.example:8090")
    me = c.get("/api/auth/me").json()["claude"]
    gh = "https://raw.githubusercontent.com/Seafinai/artifact-buckets/main/connect"
    srv = "https://files.example.lan:8443"
    assert me["unix"] == f"curl -fsSL {gh}/connect.sh | sh -s -- {srv} {sha}"
    assert me["windows"] == f"& ([scriptblock]::Create((irm {gh}/connect.ps1))) {srv} {sha}"
    assert me["uninstall_unix"] == f"curl -fsSL {gh}/connect.sh | sh -s -- {srv} {sha} remove"
    assert me["uninstall_windows"].endswith(f"{srv} {sha} remove")
    assert me["prompt"] == f"Set up Artifact Buckets on this computer by following {gh}/README.md for the server {srv} with certificate fingerprint {sha}"
    assert me["remove_prompt"].startswith("Remove Artifact Buckets") and sha in me["remove_prompt"]
    for line in (me["unix"], me["windows"], me["uninstall_unix"], me["uninstall_windows"], me["prompt"], me["remove_prompt"]):
        assert "http://" not in line
    # The connect script's address can be moved (a mirror inside a closed network).
    c2, _, _ = _private_ca(env, monkeypatch, tmp_path, AB_CONNECT_URL="https://mirror.example/ab/")
    assert c2.get("/api/auth/me").json()["claude"]["unix"].startswith("curl -fsSL https://mirror.example/ab/connect.sh | sh -s -- ")


def test_private_ca_refuses_setup_scripts_over_plain_http(env, monkeypatch, tmp_path):
    c, _, sha = _private_ca(env, monkeypatch, tmp_path)
    https = TestClient(c.app, base_url="https://testserver")
    for path in ("/claude/install.ps1", "/claude/install.sh", "/claude/uninstall.ps1", "/claude/uninstall.sh",
                 "/claude/sync.ps1", "/claude/sync.sh", "/claude/setup.md"):
        r = c.get(path)
        assert r.status_code == 410 and "Connect page" in r.text, path
        assert https.get(path).status_code == 200, path
    # Behind the proxy, the scheme comes from X-Forwarded-Proto (uvicorn --proxy-headers).
    md = https.get("/claude/setup.md").text
    assert "connect.sh" in md and sha in md and "http://" not in md


def test_public_certificate_keeps_its_own_lines(env, monkeypatch):
    c = _client(env, monkeypatch)
    me = c.get("/api/auth/me").json()["claude"]
    assert me["unix"] == "curl -fsSL http://testserver/claude/install.sh | sh" and me["fingerprint"] is None
    assert c.get("/claude/install.sh").status_code == 200


def test_plugin_connection_gets_a_plain_name(env, monkeypatch):
    c = _client(env, monkeypatch)
    r = c.post("/oauth/register", json={"client_name": "Claude Code (plugin:artifact-buckets:artifact-buckets)",
                                         "redirect_uris": ["http://localhost:4242/callback"]})
    assert r.status_code in (200, 201)
    from app.db import OAuthClient, new_session
    with new_session() as db:
        assert db.get(OAuthClient, r.json()["client_id"]).name == "Claude Code"


def test_setup_page_for_claude(env, monkeypatch, tmp_path):
    c = _client(env, monkeypatch, AB_INSTALL_URL="http://boot.example:8090")
    md = c.get("/claude/setup.md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    t = md.text
    assert "claude plugin marketplace add http://testserver/claude/marketplace.json" in t
    assert "claude mcp login plugin:artifact-buckets:artifact-buckets" in t
    assert "certificate" not in t.split("## 1.")[1].split("\n")[0].lower()  # no trust step with a public certificate
    assert c.get("/api/auth/me").json()["claude"]["prompt"] == \
        "Set up Artifact Buckets on this computer by following http://boot.example:8090/claude/setup.md"
