"""File uploads and downloads over MCP: the `io.modelcontextprotocol/files` extension (draft, beta).

A client that supports it attaches a real file to a tool call instead of pasting its text or base64 into
the conversation. Small files travel inline. Larger ones go out of band:

  1. Claude calls save_file with the file's metadata only. We run every check that doesn't need the bytes
     (where it goes, who may write there, size, quota) and answer `upload_required` with one upload target.
  2. Claude PUTs the bytes to {MCP address}/uploads/<slot>, with its usual sign-in token. They wait in the
     tree's .staging folder.
  3. Claude repeats the call with the `requestState` we gave it. We check that state (signed, bound to this
     person, tool and arguments, used once), check the bytes (size, and digest when given), and save.

Downloads work the other way: download_file lists a target at {MCP address}/downloads/<token> in the
result's _meta, and Claude fetches it with a GET.

Targets are `path` targets with `credentials: "include"`: they live on this server's own origin and need
the same token as every MCP call, so nothing here hands out a URL that works without signing in.
Spec: github.com/modelcontextprotocol/experimental-ext-file-uploads (draft). Claude's docs:
claude.com/docs/connectors/building/files.
"""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import json
import os
import re
import secrets
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import audit, config, fs, paths, routing
from .db import UploadSlot, new_session, utcnow
from .errors import AppError, BadRequest
from .perms import Actor

EXT = "io.modelcontextprotocol/files"
CLIENT_CAPS = "io.modelcontextprotocol/clientCapabilities"
MAX_INLINE_BYTES = 4 * 1024 * 1024        # total decoded inline data in one call
UPLOAD_MINUTES = 25                        # Claude expects at least 20
STATE_MINUTES = 60                         # requestState, and the staged bytes it points at
DOWNLOAD_MINUTES = 60
STATE_SALT = "ab-files-state"
DOWNLOAD_SALT = "ab-files-download"
FILE_TOOLS = ("save_file", "download_file")

router = APIRouter()


class MissingCapability(Exception):
    """The call needs a client capability it didn't declare (JSON-RPC -32021, sent as HTTP 400)."""

    def __init__(self, needed: str):
        super().__init__(needed)
        self.needed = needed

    def body(self) -> dict[str, Any]:
        return {"error": {"code": -32021, "message": f"This call needs the client's {EXT} {self.needed} capability",
                          "data": {"requiredCapabilities": {"extensions": {EXT: {self.needed: {}}}}}}}


class BadState(Exception):
    """requestState failed verification, was already used, or doesn't match the call (JSON-RPC -32602)."""


# ---- capabilities -----------------------------------------------------------

def server_settings() -> dict[str, Any]:
    return {"upload": {}, "maxInlineBytes": MAX_INLINE_BYTES}


def client_settings(params: dict[str, Any]) -> dict[str, Any] | None:
    """What the request declared for this extension, or None. An unknown revision counts as nothing."""
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return None
    caps = meta.get(CLIENT_CAPS)
    ext = caps.get("extensions") if isinstance(caps, dict) else None
    s = ext.get(EXT) if isinstance(ext, dict) else None
    if not isinstance(s, dict) or s.get("revision") not in (None,):
        return None
    return s


# ---- tool definitions ------------------------------------------------------------

def _file_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": "The file to save.",
        "x-mcp-file": {"maxSize": config.settings.max_file_bytes},
        "properties": {
            "id": {"type": "string", "minLength": 1, "maxLength": 128},
            "name": {"type": "string"},
            "mimeType": {"type": "string"},
            "size": {"type": "integer", "minimum": 0},
            "digest": {"type": "object", "properties": {"algorithm": {"const": "sha-256"}, "value": {"type": "string"}},
                       "required": ["algorithm", "value"]},
            "data": {"type": "string"},
        },
        "required": ["id", "mimeType", "size"],
    }


def tool_defs(writable: bool) -> list[dict[str, Any]]:
    s = {"type": "string"}
    out = []
    if writable:
        out.append({
            "name": "save_file",
            "title": "Save a file",
            "description": "Save a file (any kind: documents, spreadsheets, slides, images, PDFs, archives) into Artifact "
                           "Buckets. Give `folder` or a full `path`; with neither, it goes to the person's inbox, or their "
                           "project folder when you give `project`. `name` overrides the file's own name. Saving the "
                           "same path again makes a new version.",
            "inputSchema": {"type": "object", "properties": {
                "file": _file_schema(),
                "name": {**s, "description": "File name to save as, e.g. q3-board-deck.pptx (default: the file's own name)"},
                "folder": {**s, "description": "Folder to save into, e.g. /shared/finance/reports"},
                "path": {**s, "description": "Full path including the file name"},
                "project": {**s, "description": "Project name, used to route the file when no folder is given"},
                "tags": {"type": "array", "items": s},
                "if_version": {"type": "integer", "minimum": 1,
                               "description": "Only save if the file is still at this version"},
            }, "required": ["file"], "additionalProperties": False},
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        })
    out.append({
        "name": "download_file",
        "title": "Get a copy of a file",
        "description": "Hand the person (or your own workspace) a copy of a file from Artifact Buckets, any size or type. "
                       "Use get_artifact instead when you only need to read a text file's contents.",
        "inputSchema": {"type": "object", "properties": {"path": {**s, "description": "The file's full path"}},
                        "required": ["path"], "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    })
    return out


# ---- helpers -----------------------------------------------------------------------

def _b64url_sha256(hexdigest: str) -> str:
    return base64.urlsafe_b64encode(bytes.fromhex(hexdigest)).rstrip(b"=").decode()


def _args_hash(name: str, args: dict[str, Any]) -> str:
    """JSON Schema instance equality: member order and number spelling don't matter."""
    def norm(v: Any) -> Any:
        if isinstance(v, bool) or v is None or isinstance(v, str):
            return v
        if isinstance(v, (int, float)):
            return int(v) if float(v).is_integer() else float(v)
        if isinstance(v, list):
            return [norm(x) for x in v]
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items()}
        return v
    raw = json.dumps([name, norm(args)], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _file_input(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise BadRequest("file must be an object with id, mimeType and size")
    allowed = {"id", "name", "mimeType", "size", "digest", "data"}
    extra = set(v) - allowed
    if extra:
        raise BadRequest(f"Unknown file field: {sorted(extra)[0]}")
    fid, mime, size = v.get("id"), v.get("mimeType"), v.get("size")
    if not isinstance(fid, str) or not 1 <= len(fid) <= 128:
        raise BadRequest("file.id must be 1 to 128 characters")
    if not isinstance(mime, str) or not mime or len(mime) > 255:
        raise BadRequest("file.mimeType is required")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > 2 ** 53:
        raise BadRequest("file.size must be a whole number of bytes")
    if v.get("name") is not None and not isinstance(v["name"], str):
        raise BadRequest("file.name must be a string")
    dg = v.get("digest")
    if dg is not None:
        if not isinstance(dg, dict) or dg.get("algorithm") != "sha-256" or not isinstance(dg.get("value"), str):
            raise BadRequest("file.digest must be {algorithm: sha-256, value}")
    if "data" in v and not isinstance(v["data"], str):
        raise BadRequest("file.data must be base64 text")
    return v


def _base_name(name: str | None) -> str:
    b = re.split(r"[/\\]", name or "")[-1].strip()
    return "" if b in ("", ".", "..") else b


def _destination(db: Session, actor: Actor, a: dict[str, Any], f: dict[str, Any]) -> tuple[str, str]:
    if a.get("path"):
        return paths.normalize(a["path"]), "path"
    name = a.get("name") or _base_name(f.get("name"))
    if not name:
        raise BadRequest("The file has no name: give `name` or a full `path`")
    if "/" in name or "\\" in name:
        raise BadRequest("name is a file name, not a path")
    folder, reason = routing.resolve(db, actor, folder=a.get("folder"), project=a.get("project"), git_remote=None)
    return paths.join(folder, name), reason


def _check_digest(f: dict[str, Any], sha_hex: str) -> bool:
    dg = f.get("digest")
    return dg is None or secrets.compare_digest(dg["value"].rstrip("="), _b64url_sha256(sha_hex))


def _result(res: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(res, default=str, indent=1)
    return {"content": [{"type": "text", "text": text}], "structuredContent": res, "isError": False}


def _error(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": True}


# ---- tools/call ----------------------------------------------------------------------

def call(db: Session, actor: Actor, name: str, args: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Run save_file or download_file. Returns a JSON-RPC result. Raises MissingCapability or BadState."""
    caps = client_settings(params) or {}
    try:
        if name == "save_file":
            return _save(db, actor, args, params, caps)
        return _download(db, actor, args, caps)
    except AppError as e:
        db.rollback()
        return _error(f"{e.code}: {e.message}")
    except NotADirectoryError:
        db.rollback()
        return _error("conflict: Part of that path is a file, not a folder")


def _save(db: Session, actor: Actor, a: dict[str, Any], params: dict[str, Any], caps: dict[str, Any]) -> dict[str, Any]:
    from .mcp import check_if_version, link
    if actor.token is not None and actor.token.scope == "read":
        return _error("forbidden: This sign-in can only read")
    allowed = {"file", "name", "folder", "path", "project", "tags", "if_version"}
    for k in a:
        if k not in allowed:
            raise BadRequest(f"Unknown argument: {k}")
    if "file" not in a:
        raise BadRequest("Missing argument: file")
    f = _file_input(a["file"])
    meta = fs.SaveMeta(source="mcp", project=a.get("project"),
                       tags=a.get("tags") if isinstance(a.get("tags"), list) else None)
    state = params.get("requestState")

    if state is not None:  # the retry after an out-of-band upload
        from .security import unsign
        st = unsign(state, STATE_SALT, max_age=STATE_MINUTES * 60) if isinstance(state, str) else None
        if (st is None or st.get("t") != "save_file" or st.get("u") != actor.user.id
                or st.get("a") != _args_hash("save_file", a)):
            raise BadState("requestState is not valid for this call")
        slot = db.get(UploadSlot, st.get("s"))
        if slot is None or slot.state == "used" or slot.user_id != actor.user.id:
            raise BadState("requestState was already used")
        if slot.state != "stored":
            return _error("not_found: The file didn't arrive, so nothing was saved. Send it again.")
        staged = _staged(slot.id)
        if not os.path.isfile(staged) or os.path.getsize(staged) != f["size"] or slot.size != f["size"]:
            return _error("bad_request: The file that arrived isn't the size that was announced. Nothing was saved.")
        if not _check_digest(f, slot.sha256 or ""):
            return _error("bad_request: The file that arrived doesn't match its digest. Nothing was saved.")
        # Use the state once: a second retry can't save a second version.
        n = db.execute(update(UploadSlot).where(UploadSlot.id == slot.id, UploadSlot.state == "stored")
                       .values(state="used")).rowcount
        db.commit()
        if n != 1:
            raise BadState("requestState was already used")
        with open(staged, "rb") as fh:
            data = fh.read()
        try:
            os.unlink(staged)
        except OSError:
            pass
        path, reason = st["p"], st["r"]
        if a.get("if_version") is not None:
            check_if_version(db, path, int(a["if_version"]))
        res = fs.save_file(db, actor, path, data, meta)
        return _result({**res, "routed_by": reason, "link": link(path)})

    path, reason = _destination(db, actor, a, f)
    if "data" in f or f["size"] == 0:  # inline, or an empty file
        raw = f.get("data") or ""
        if len(raw) > MAX_INLINE_BYTES * 4 // 3 + 8:
            return _error(f"too_large: Inline files can be up to {MAX_INLINE_BYTES // (1024 * 1024)} MB; send it as an upload")
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            return _error("bad_request: file.data is not valid base64")
        if len(data) != f["size"]:
            return _error("bad_request: file.data doesn't match file.size")
        if not _check_digest(f, hashlib.sha256(data).hexdigest()):
            return _error("bad_request: file.data doesn't match its digest")
        if a.get("if_version") is not None:
            check_if_version(db, path, int(a["if_version"]))
        res = fs.save_file(db, actor, path, data, meta)
        return _result({**res, "routed_by": reason, "link": link(path)})

    # Out of band: accept or refuse on the metadata, then ask for the bytes.
    if "upload" not in caps:
        raise MissingCapability("upload")
    path = fs.check_save(db, actor, path, f["size"], meta)
    if a.get("if_version") is not None:
        check_if_version(db, path, int(a["if_version"]))
    now = utcnow()
    slot = UploadSlot(id=secrets.token_hex(16), user_id=actor.user.id, path=path, size=f["size"],
                      mime=f["mimeType"][:255], expires_at=now + dt.timedelta(minutes=STATE_MINUTES))
    db.add(slot)
    db.commit()
    from .security import sign
    state = sign({"t": "save_file", "u": actor.user.id, "a": _args_hash("save_file", a), "s": slot.id,
                  "p": path, "r": reason}, STATE_SALT)
    target: dict[str, Any] = {"fileId": f["id"], "path": f"/uploads/{slot.id}", "method": "PUT",
                              "credentials": "include",
                              "expiresAt": (now + dt.timedelta(minutes=UPLOAD_MINUTES)).replace(microsecond=0).isoformat() + "Z"}
    if _valid_media_type(f["mimeType"]):
        target["headers"] = {"Content-Type": f["mimeType"]}
    return {"resultType": "upload_required", "uploads": [target], "requestState": state}


def _valid_media_type(m: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+(\s*;\s*[A-Za-z0-9!#$&^_.+-]+=(\"[^\"\r\n]*\"|[A-Za-z0-9!#$&^_.+-]+))*", m))


def _download(db: Session, actor: Actor, a: dict[str, Any], caps: dict[str, Any]) -> dict[str, Any]:
    from .mcp import link
    if set(a) - {"path"} or not isinstance(a.get("path"), str):
        raise BadRequest("Give the file's path")
    if "download" not in caps:
        raise MissingCapability("download")
    _, f = fs.open_file(db, actor, a["path"])
    from .security import sign
    tok = sign({"u": actor.user.id, "p": f.path, "h": f.sha256}, DOWNLOAD_SALT)
    expires = (utcnow() + dt.timedelta(minutes=DOWNLOAD_MINUTES)).replace(microsecond=0).isoformat() + "Z"
    target = {"name": paths.name(f.path), "mimeType": f.mime or "application/octet-stream", "size": f.size,
              "digest": {"algorithm": "sha-256", "value": _b64url_sha256(f.sha256)},
              "path": f"/downloads/{tok}", "credentials": "include", "expiresAt": expires}
    info = {"path": f.path, "name": paths.name(f.path), "size": f.size, "mime": f.mime, "version": f.version,
            "link": link(f.path)}
    return {"resultType": "complete",
            "content": [{"type": "text", "text": f"Sending {info['name']} (version {f.version}, {f.size} bytes)."}],
            "structuredContent": info, "isError": False,
            "_meta": {EXT: {"downloads": [target]}}}


# ---- the targets ---------------------------------------------------------------------

def _staged(slot_id: str) -> str:
    return os.path.join(paths.system_dir("staging"), slot_id)


def _auth(db: Session, request: Request) -> Actor | None:
    from .mcp import authenticate
    return authenticate(db, request)


def _plain(status: int, msg: str) -> Response:
    return JSONResponse({"error": msg}, status_code=status, headers={"Cache-Control": "no-store"})


@router.put("/mcp/uploads/{slot_id}")
async def upload(slot_id: str, request: Request) -> Response:
    if not re.fullmatch(r"[0-9a-f]{32}", slot_id):
        return _plain(404, "No such upload")
    with new_session() as db:
        actor = _auth(db, request)
        if actor is None:
            return _plain(401, "Sign in required")
        if actor.token is not None and actor.token.scope == "read":
            return _plain(403, "This sign-in can only read")
        slot = db.get(UploadSlot, slot_id)
        if slot is None or slot.user_id != actor.user.id:
            return _plain(404, "No such upload")
        if slot.state != "pending" or slot.expires_at < utcnow():
            return _plain(409, "This upload was already used or has expired")
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) != slot.size:
            return _plain(400, "Content-Length doesn't match the announced size")
        size = slot.size
    dest = _staged(slot_id)
    tmp = dest + ".part"
    h, n = hashlib.sha256(), 0
    try:
        with open(tmp, "wb") as fh:
            async for chunk in request.stream():
                n += len(chunk)
                if n > size:
                    raise ValueError("too large")
                h.update(chunk)
                fh.write(chunk)
        if n != size:
            raise ValueError("short")
    except (ValueError, OSError):
        _rm(tmp)
        return _plain(400 if n <= size else 413, "The file isn't the size that was announced")
    except Exception:  # client went away mid-upload
        _rm(tmp)
        raise
    with new_session() as db:
        # One write only: the first complete upload wins.
        ok = db.execute(update(UploadSlot).where(UploadSlot.id == slot_id, UploadSlot.state == "pending")
                        .values(state="stored", sha256=h.hexdigest())).rowcount
        db.commit()
    if ok != 1:
        _rm(tmp)
        return _plain(409, "This upload was already used")
    os.replace(tmp, dest)
    return Response(status_code=201, headers={"Cache-Control": "no-store"})


@router.get("/mcp/downloads/{token}")
def download(token: str, request: Request) -> Response:
    from .security import unsign
    st = unsign(token, DOWNLOAD_SALT, max_age=DOWNLOAD_MINUTES * 60)
    with new_session() as db:
        actor = _auth(db, request)
        if actor is None:
            return _plain(401, "Sign in required")
        if st is None or st.get("u") != actor.user.id:
            return _plain(404, "No such download, or it has expired")
        try:
            d, f = fs.open_file(db, actor, st["p"])  # permission checked again, now
        except AppError:
            return _plain(404, "No such download, or it has expired")
        if f.sha256 != st.get("h"):
            return _plain(410, "The file changed after this link was made; ask for it again")
        audit.log(db, actor, "file.download", f.path, version=f.version, size=f.size)
        db.commit()
        return FileResponse(d, media_type=f.mime or "application/octet-stream",
                            headers={"ETag": f'"{f.sha256}"', "Cache-Control": "private, no-store",
                                     "X-Content-Type-Options": "nosniff",
                                     "Content-Disposition": "attachment"})


def _rm(p: str) -> None:
    try:
        os.unlink(p)
    except OSError:
        pass


def purge_expired(db: Session) -> int:
    """Housekeeping: forget upload slots past their requestState, and their staged bytes."""
    n = 0
    for s in list(db.scalars(select(UploadSlot).where(UploadSlot.expires_at < utcnow()))):
        _rm(_staged(s.id))
        _rm(_staged(s.id) + ".part")
        db.delete(s)
        n += 1
    db.commit()
    return n
