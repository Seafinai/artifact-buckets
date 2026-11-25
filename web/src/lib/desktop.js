// The Claude Desktop extension: made for the signed-in person on this server, downloaded as a file they open once.
import { session } from './session.svelte.js';

export async function downloadDesktopExtension() {
  const r = await fetch('/api/claude/desktop-extension', { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': session.csrf } });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).message || `Download failed (${r.status})`);
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement('a'), { href: url, download: 'artifact-buckets.mcpb' });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
