# Claude's apps: web, desktop and mobile

Artifact Buckets works as a **custom connector** in Claude. Once someone connects it, Claude can save what it
makes into their folders, find and open earlier work, and share folders, in any chat, with the same permissions
they have in the web app. Admins also get the admin tools, as they do in Claude Code.

What it needs: a public `https` address with a trusted certificate, because Claude's apps reach connectors from
the internet. [public-https.md](public-https.md) sets one up with a Cloudflare Tunnel. **Connect Claude** in the
web app shows the connector address and the steps once the address is public, and says what's missing until then.

## Sign-in

Claude signs in the way Claude Code does (OAuth 2.1 with PKCE and dynamic client registration). The difference is
where the browser goes back to: Claude's apps finish sign-in at `https://claude.ai/api/mcp/auth_callback`. The
server allows that one exact address (and its `claude.com` twin) and no other address on those sites. To turn
Claude's apps off on a server, set `AB_CLAUDE_WEB=false`.

The consent page names Claude, not a computer. Each connection is listed under **Connect Claude** as *Claude on
the web*, with the same 30-day sign-in, audit trail and **Disconnect** button as a Claude Code computer.

## Files, not only text

Through the connector, Claude saves anything it writes as text with `save_artifact`: documents, code, CSV, HTML,
SVG. Binary files go through the same tool as base64, which works for small files.

For real files, such as a PDF someone attached or a slide deck Claude generated, there is a newer, open protocol:
the MCP files extension (`io.modelcontextprotocol/files`, a draft). Claude added a beta feature on top of it on
2026-11-24 that sends files to connected apps and saves files from them. Artifact Buckets implements the
extension:

| | |
|---|---|
| Discovery | `server/discover` answers without a sign-in and lists the extension, with uploads and 4 MB inline. |
| `save_file` | Takes an `x-mcp-file` argument. Small files arrive inline. Larger ones: the server first checks where the file goes, the person's access, the size and the quota, then answers `upload_required` with one upload target. |
| Upload target | `PUT {MCP address}/uploads/<id>` on the server's own origin, with the same sign-in token as the MCP call (`credentials: include`). It takes exactly the announced size, once, within 25 minutes. Bytes wait in the hidden `.staging` folder. |
| Retry | Claude repeats the call with the `requestState` it was given. The state is signed, bound to the person, the tool and its arguments, expires after an hour, and works once, so a repeated retry can't save a second version. The server checks the size (and the SHA-256 digest when Claude sends one) before it saves. |
| `download_file` | Lists a download target in the result's `_meta` at `GET {MCP address}/downloads/<token>`, with the size and SHA-256. The link needs the same sign-in, expires in an hour, checks access again when used, and stops working if the file changes. Range requests work. |

The file tools only appear for clients that declare the extension, as the draft asks.

**Why Claude doesn't use it here yet.** Claude's file transfers only work with apps listed in Claude's connectors
directory, at the exact address on the listing, and with file storage hosts that Anthropic has approved.
Connectors added by their own URL get no files, and Claude removes files from their results. A self-hosted server
has a different address at every company, so it can't be that listing today. Sources:
[Claude's developer docs on file transfers](https://claude.com/docs/connectors/building/files) and the
[help center article](https://support.claude.com/en/articles/18534325).

So for now, Claude's apps save through `save_artifact`, and the file tools are ready for when Claude (or another
MCP client) sends files to self-hosted servers. The extension is a draft and Claude's feature is a beta, so
expect changes on both sides.
