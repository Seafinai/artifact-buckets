"""The Claude Desktop extension download: a bundle made for one person, whose first token rotates on first use."""
import io
import json
import zipfile

from conftest import MCP


def test_download_builds_a_bundle_for_the_person(app, make_user):
    jo = make_user("jo")
    r = jo.post("/api/claude/desktop-extension")
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].endswith('"artifact-buckets.mcpb"')
    z = zipfile.ZipFile(io.BytesIO(r.content))
    man = json.loads(z.read("manifest.json"))
    assert man["manifest_version"] == "0.3" and man["server"]["type"] == "node"
    assert man["server"]["mcp_config"]["args"] == ["${__dirname}/server/index.js"]
    assert b"forward" in z.read("server/index.js")
    conf = json.loads(z.read("server/config.json"))
    assert conf["refresh_token"].startswith("ab_rt_") and conf["client_id"].startswith("abd_")

    # It shows up as a connection, named for what it is.
    toks = jo.get("/api/tokens").json()["tokens"]
    assert any(t["name"] == "Claude Desktop" for t in toks)

    # The extension's first refresh rotates the token; the one in the file then stops working and revoking it ends
    # the sign-in (someone else holding a copy of the download gets nothing once it's been used).
    c = jo.c
    t1 = c.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": conf["refresh_token"], "client_id": conf["client_id"]})
    assert t1.status_code == 200, t1.text
    access = t1.json()["access_token"]
    assert MCP(app, access).tools()
    again = c.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": conf["refresh_token"], "client_id": conf["client_id"]})
    assert again.status_code == 400
    assert c.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": t1.json()["refresh_token"], "client_id": conf["client_id"]}).status_code == 400


def test_download_needs_a_browser_session(app, make_user):
    jo = make_user("jo")
    r = jo.c.post("/api/claude/desktop-extension")
    assert r.status_code == 403
