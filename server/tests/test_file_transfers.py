"""MCP file uploads and downloads (the io.modelcontextprotocol/files extension), and Claude on the web sign-in."""
import base64
import hashlib

from fastapi.testclient import TestClient

from conftest import oauth_sign_in

EXT = "io.modelcontextprotocol/files"
BOTH = {"io.modelcontextprotocol/clientCapabilities": {"extensions": {EXT: {"upload": {}, "download": {}}}}}


def b64url_sha(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


class Client:
    """An MCP client that speaks the files extension."""

    def __init__(self, app, token, meta=BOTH):
        self.c = TestClient(app)
        self.h = {"Authorization": f"Bearer {token}"}
        self.meta, self.n = meta, 0

    def post(self, method, params):
        self.n += 1
        p = {**params, "_meta": self.meta} if self.meta else params
        return self.c.post("/mcp", json={"jsonrpc": "2.0", "id": self.n, "method": method, "params": p}, headers=self.h)

    def call(self, name, args, **extra):
        r = self.post("tools/call", {"name": name, "arguments": args, **extra})
        assert r.status_code == 200, r.text
        return r.json()

    def put(self, target, data):
        assert target["path"].startswith("/uploads/") and target["credentials"] == "include"
        return self.c.put("/mcp" + target["path"], content=data, headers={**self.h, **target.get("headers", {})})


def fin(data, fid="file-1", name="Q3 report.pdf", mime="application/pdf", digest=True):
    f = {"id": fid, "name": name, "mimeType": mime, "size": len(data)}
    if digest:
        f["digest"] = {"algorithm": "sha-256", "value": b64url_sha(data)}
    return f


def test_discover_without_sign_in(app):
    r = TestClient(app).post("/mcp", json={"jsonrpc": "2.0", "id": 7, "method": "server/discover", "params": {}})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["capabilities"]["extensions"][EXT]["upload"] == {}
    assert "2026-07-28" in res["supportedVersions"]
    # Anything else still needs a sign-in.
    r = TestClient(app).post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert r.status_code == 401


def test_file_tools_only_for_clients_that_declare_it(app, make_user):
    t = oauth_sign_in(app, make_user("alice"))
    plain = Client(app, t["access_token"], meta=None)
    names = [x["name"] for x in plain.post("tools/list", {}).json()["result"]["tools"]]
    assert "save_file" not in names and "save_artifact" in names
    tools = {x["name"]: x for x in Client(app, t["access_token"]).post("tools/list", {}).json()["result"]["tools"]}
    schema = tools["save_file"]["inputSchema"]
    assert "x-mcp-file" in schema["properties"]["file"] and "x-mcp-file" not in schema
    assert not {"anyOf", "allOf", "oneOf"} & set(schema)
    assert "download_file" in tools


def test_out_of_band_upload_then_retry_saves(app, make_user):
    t = oauth_sign_in(app, make_user("alice"))
    c = Client(app, t["access_token"])
    data = b"%PDF-1.7\n" + bytes(range(256)) * 40
    args = {"file": fin(data), "folder": "/users/alice/inbox"}
    first = c.call("save_file", args)["result"]
    assert first["resultType"] == "upload_required"
    (target,) = first["uploads"]
    assert target["fileId"] == "file-1" and target["method"] == "PUT" and target["headers"] == {"Content-Type": "application/pdf"}
    # Nothing is saved yet, and nothing for someone else's token.
    bob = oauth_sign_in(app, make_user("bob"))
    assert Client(app, bob["access_token"]).put(target, data).status_code == 404
    assert c.c.put("/mcp" + target["path"], content=data).status_code == 401
    assert c.put(target, data[:-1]).status_code == 400  # short
    assert c.put(target, data).status_code == 201
    assert c.put(target, data).status_code == 409       # one write only
    # The retry: same arguments (member order doesn't matter), echoed state.
    reordered = {"folder": "/users/alice/inbox", "file": dict(reversed(list(fin(data).items())))}
    done = c.call("save_file", reordered, requestState=first["requestState"])["result"]
    assert not done["isError"], done
    assert done["structuredContent"]["path"] == "/users/alice/inbox/Q3 report.pdf"
    assert done["structuredContent"]["size"] == len(data)
    # Used once: a repeated retry is refused, and doesn't make a second version.
    again = c.call("save_file", reordered, requestState=first["requestState"])
    assert again["error"]["code"] == -32602
    # And it downloads back byte for byte.
    got = c.call("download_file", {"path": "/users/alice/inbox/Q3 report.pdf"})["result"]
    (dl,) = got["_meta"][EXT]["downloads"]
    assert "downloads" not in str(got["structuredContent"]) and dl["path"] not in got["content"][0]["text"]
    assert dl["size"] == len(data) and dl["digest"]["value"] == b64url_sha(data)
    r = c.c.get("/mcp" + dl["path"], headers=c.h)
    assert r.status_code == 200 and r.content == data
    assert c.c.get("/mcp" + dl["path"]).status_code == 401
    assert Client(app, bob["access_token"]).c.get("/mcp" + dl["path"], headers={"Authorization": f"Bearer {bob['access_token']}"}).status_code == 404


def test_retry_must_match_the_call(app, make_user):
    t = oauth_sign_in(app, make_user("alice"))
    c = Client(app, t["access_token"])
    data = b"x" * 5000
    args = {"file": fin(data, name="a.bin", mime="application/octet-stream"), "folder": "/users/alice/inbox"}
    first = c.call("save_file", args)["result"]
    assert c.put(first["uploads"][0], data).status_code == 201
    changed = {**args, "folder": "/users/alice/projects"}
    assert c.call("save_file", changed, requestState=first["requestState"])["error"]["code"] == -32602
    assert c.call("save_file", args, requestState="tampered")["error"]["code"] == -32602
    bob = oauth_sign_in(app, make_user("bob"))
    assert Client(app, bob["access_token"]).call("save_file", args, requestState=first["requestState"])["error"]["code"] == -32602
    assert not c.call("save_file", args, requestState=first["requestState"])["result"]["isError"]


def test_digest_mismatch_and_missing_bytes_save_nothing(app, make_user):
    t = oauth_sign_in(app, make_user("alice"))
    c = Client(app, t["access_token"])
    data = b"y" * 3000
    f = {**fin(data, name="d.bin"), "digest": {"algorithm": "sha-256", "value": b64url_sha(b"other")}}
    args = {"file": f, "folder": "/users/alice/inbox"}
    first = c.call("save_file", args)["result"]
    res = c.call("save_file", args, requestState=first["requestState"])["result"]  # bytes never sent
    assert res["isError"] and "didn't arrive" in res["content"][0]["text"]
    assert c.put(first["uploads"][0], data).status_code == 201
    res = c.call("save_file", args, requestState=first["requestState"])["result"]
    assert res["isError"] and "digest" in res["content"][0]["text"]
    lst = c.call("list_folder", {"path": "/users/alice/inbox"})["result"]
    assert "d.bin" not in lst["content"][0]["text"]


def test_refused_on_metadata_before_any_bytes(app, make_user):
    t = oauth_sign_in(app, make_user("alice"))
    make_user("bob")
    c = Client(app, t["access_token"])
    res = c.call("save_file", {"file": fin(b"z" * 100), "folder": "/users/bob/inbox"})["result"]
    assert res["isError"] and "resultType" not in res
    from app import config
    big = {"id": "f", "name": "huge.iso", "mimeType": "application/octet-stream", "size": config.settings.max_file_bytes + 1}
    res = c.call("save_file", {"file": big})["result"]
    assert res["isError"] and "too_large" in res["content"][0]["text"]


def test_inline_and_empty_files(app, make_user):
    t = oauth_sign_in(app, make_user("alice"))
    # Inline works even when the request didn't declare the extension.
    c = Client(app, t["access_token"], meta=None)
    data = b"name,total\nnorth,12\n"
    f = {**fin(data, name="totals.csv", mime="text/csv"), "data": base64.b64encode(data).decode()}
    res = c.call("save_file", {"file": f, "project": "Quarterly Review"})["result"]
    assert not res["isError"], res
    assert res["structuredContent"]["path"] == "/users/alice/projects/quarterly-review/totals.csv"
    bad = {**f, "size": len(data) + 1}
    assert c.call("save_file", {"file": bad})["result"]["isError"]
    empty = {"id": "e", "name": "empty.txt", "mimeType": "text/plain", "size": 0}
    assert not c.call("save_file", {"file": empty})["result"]["isError"]


def test_missing_capability_is_minus_32021(app, make_user):
    t = oauth_sign_in(app, make_user("alice"))
    c = Client(app, t["access_token"], meta=None)
    c.n += 1
    r = c.c.post("/mcp", headers=c.h, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "save_file", "arguments": {"file": fin(b"q" * 10)}}})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32021
    assert "jsonrpc" not in r.json()
    r = c.c.post("/mcp", headers=c.h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "download_file", "arguments": {"path": "/users/alice/inbox/x"}}})
    assert r.status_code == 400 and r.json()["error"]["data"]["requiredCapabilities"]["extensions"][EXT] == {"download": {}}


def test_claude_web_sign_in(app, make_user):
    """claude.ai, Claude Desktop and mobile sign in through Claude's hosted callback."""
    t = oauth_sign_in(app, make_user("alice"), redirect="https://claude.ai/api/mcp/auth_callback")
    assert t["access_token"].startswith("ab_at_")
    # Other https hosts still need an admin to list them.
    r = TestClient(app).post("/oauth/register", json={"redirect_uris": ["https://claude.ai.evil.example/api/mcp/auth_callback"]})
    assert r.status_code == 400
    r = TestClient(app).post("/oauth/register", json={"redirect_uris": ["https://claude.ai/somewhere/else"]})
    assert r.status_code == 400


def test_claude_web_can_be_turned_off(app, make_user, monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "claude_web", False)
    r = TestClient(app).post("/oauth/register", json={"redirect_uris": ["https://claude.ai/api/mcp/auth_callback"]})
    assert r.status_code == 400
