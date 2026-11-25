<script>
  import { api } from '../lib/api.js';
  import { session } from '../lib/session.svelte.js';
  import { toast, fail } from '../lib/toast.svelte.js';
  import { ago, agoPhrase, when } from '../lib/format.js';
  import Icon from '../lib/Icon.svelte';
  import Copy from '../lib/Copy.svelte';
  import SetupCopy from '../lib/SetupCopy.svelte';
  import { downloadDesktopExtension } from '../lib/desktop.js';
  import Modal from '../lib/Modal.svelte';

  let tokens = $state(null);
  let dialog = $state(null);
  let created = $state(null);
  let stopping = $state(null);
  let form = $state({ name: '', scope: 'write', folders: '', days: 30 });

  let everyone = $state(false);
  async function load() { try { tokens = (await api.get('/api/tokens', everyone ? { all: true } : {})).tokens; } catch (e) { fail(e); } }
  load();
  const devices = $derived((tokens || []).filter((t) => t.kind === 'device'));
  const personal = $derived((tokens || []).filter((t) => t.kind === 'personal'));
  const syncers = $derived((tokens || []).filter((t) => t.kind === 'sync'));
  let sync = $state(null);
  api.get('/api/sync/status', null, { quiet: true }).then((d) => (sync = d)).catch(() => {});
  const home = `/users/${session.user.username}`;

  async function revoke(t) {
    try {
      await api.del(`/api/tokens/${t.id}`);
      toast(t.kind === 'device' ? `Disconnected ${t.name}` : t.kind === 'sync' ? `${t.name.replace(/^Sync on /, '')} no longer syncs` : `Revoked ${t.name}`);
      load();
    } catch (e) { fail(e); }
  }
  async function create(e) {
    e.preventDefault();
    try {
      const folders = form.folders.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
      created = await api.post('/api/tokens', { name: form.name, scope: form.scope, folders: folders.length ? folders : null, days: Number(form.days) });
      dialog = null; load();
    } catch (e) { fail(e); }
  }
  const mcpUrl = `${session.base_url}/mcp`;
  const setup = session.claude || {};
  let os = $state(/Windows/i.test(navigator.userAgent) ? 'windows' : 'unix');
  const web = setup.web || { ready: false, why: 'off', url: mcpUrl };
  const host = (() => { try { return new URL(session.base_url).host; } catch { return session.base_url; } })();
  const guide = 'https://github.com/Seafinai/artifact-buckets/blob/main/docs/public-https.md';
  const isWeb = (d) => d.app === 'claude_web';
  // The Claude Desktop extension: made for this person on the server, downloaded as a file they open once.
  let busy = $state(false);
  async function desktop() {
    busy = true;
    try {
      await downloadDesktopExtension();
      toast('Downloaded. Open it to add Artifact Buckets to Claude Desktop.');
      load();
    } catch (e) { fail(e); } finally { busy = false; }
  }
  const mine = $derived(devices.filter((d) => !isWeb(d) && d.name !== 'Claude Desktop' && (!everyone || d.user === session.user.username)));
  $effect(() => { if (mine.length) return; const id = setInterval(load, 4000); return () => clearInterval(id); });
</script>

<div class="page">
  <header class="page-head"><h1>Connect Claude</h1></header>

  <section class="card desk">
    <span class="di"><Icon name="download" size={18} /></span>
    <span class="desk-t"><b>Claude desktop app</b><span>Download, open it, press Install. Made for you and this server.</span></span>
    <button class="btn pri desk-btn" onclick={desktop} disabled={busy}><Icon name="download" />{busy ? 'Preparing…' : 'Add to Claude Desktop'}</button>
  </section>

  <section class="card hero">
    <div class="hero-main">
      <div class="hero-copy">
        <span class="kind"><Icon name="terminal" size={15} />Claude Code<span class="faint">terminal, VS Code, JetBrains, and the desktop app’s Code tab</span></span>
        <SetupCopy text={setup.prompt} primary={false} />
      </div>
      <ol class="steps3">
        <li><span class="n">1</span><span><b>Copy</b> the setup</span></li>
        <li><span class="n">2</span><span><b>Paste</b> it into Claude Code on your computer</span></li>
        <li><span class="n">3</span><span>Press <b>Connect</b> on the page that opens here</span></li>
      </ol>
    </div>
    <div class="live" class:ok={mine.length}>
      {#if mine.length}
        <Icon name="check" size={15} /><span>Connected on <b>{mine[0].name}</b>{#if mine.length > 1}{' '}and {mine.length - 1} more{/if}. Saves land in <span class="mono">{home}/projects</span>.</span>
      {:else}
        <span class="pulse" aria-hidden="true"></span><span>Waiting for Claude Code to connect. This updates by itself.</span>
      {/if}
    </div>
  </section>

  {#if web.ready}
    <section class="card apps" id="web">
      <span class="ai"><Icon name="sparkle" size={16} /></span>
      <span class="apps-t"><b>Claude apps</b><span>web, desktop and phone</span></span>
      <span class="apps-how">In Claude: <b>Settings</b>, <b>Connectors</b>, <b>Add custom connector</b>, then paste</span>
      <span class="apps-act"><Copy text={web.url} label="the connector address" /></span>
    </section>
  {:else if session.isAdmin && web.why !== 'off'}
    <section class="card apps" id="web">
      <span class="ai"><Icon name="sparkle" size={16} /></span>
      <span class="apps-t"><b>Claude apps</b><span>web, desktop and phone</span></span>
      <span class="apps-how">Optional. To use these too, this server needs an address that works from the internet. Only you see this.</span>
      <a class="btn sm" href={guide} target="_blank" rel="noopener"><Icon name="external" size={14} />Ways to set it up</a>
    </section>
  {/if}

  <details class="card adv">
    <summary>Advanced</summary>
    <div class="adv-body">
      <div class="adv-sec">
        <div class="adv-h"><h3>From a terminal</h3>
          <div class="segs" role="group" aria-label="Your computer">
            <button class="seg" class:on={os === 'windows'} onclick={() => (os = 'windows')}>Windows</button>
            <button class="seg" class:on={os === 'unix'} onclick={() => (os = 'unix')}>macOS and Linux</button>
          </div>
        </div>
        <Copy text={os === 'windows' ? setup.windows : setup.unix} label="the setup command" />
        {#if setup.fingerprint}<p class="fp">This server’s certificate, checked by setup before anything is trusted: <span class="mono">{setup.fingerprint.match(/.{1,4}/g).join(' ')}</span></p>{/if}
      </div>
      <div class="adv-sec">
        <h3>The setup message</h3>
        <Copy text={setup.prompt} label="the setup message" />
      </div>
      <div class="adv-sec">
        <h3>Remove it from a computer</h3>
        <Copy text={os === 'windows' ? setup.uninstall_windows : setup.uninstall_unix} label="the remove command" />
        <p class="note">Files already saved stay in your folders.</p>
      </div>
      {#if session.isAdmin}
        <div class="adv-sec">
          <div class="adv-h"><h3>Every computer at once <span class="faint">Intune, Group Policy, Jamf</span></h3>
            <a class="btn sm" href="/claude/managed-settings.json" download="managed-settings.json"><Icon name="download" size={14} />Policy file</a></div>
          <dl class="where">
            <dt>Windows</dt><dd class="mono">C:\Program Files\ClaudeCode\managed-settings.json</dd>
            <dt>Group Policy or Intune</dt><dd>The same JSON as the <span class="mono">Settings</span> value under <span class="mono">HKLM\SOFTWARE\Policies\ClaudeCode</span></dd>
            <dt>macOS</dt><dd class="mono">/Library/Application Support/ClaudeCode/managed-settings.json</dd>
            <dt>Linux</dt><dd class="mono">/etc/claude-code/managed-settings.json</dd>
          </dl>
        </div>
      {/if}
      <div class="adv-sec">
        <div class="adv-h"><h3>Personal tokens <span class="faint">for build servers and scripts</span></h3>
          <span class="row" style="gap:8px">
            {#if session.isAdmin}<button class="btn sm" onclick={() => { everyone = true; load(); }}><Icon name="users" size={14} />Everyone’s connections</button>{/if}
            <button class="btn sm" onclick={() => { form = { name: '', scope: 'write', folders: '', days: 30 }; dialog = 'new'; }}><Icon name="key" size={14} />New token</button>
          </span></div>
      </div>
      <div class="adv-sec">
        <h3>By hand</h3>
        <Copy text={`claude plugin marketplace add ${setup.marketplace}`} />
        <Copy text={`claude plugin install ${setup.plugin}`} />
        <p class="note">Then in Claude Code: <code>/mcp</code>, <b>artifact-buckets</b>, <b>Authenticate</b>.</p>
      </div>
    </div>
  </details>

  {#if devices.length || everyone}
  <section class="card">
    <div class="hd">
      <h2>{everyone ? 'Everyone’s connections' : 'Your connections'}</h2>
      <span class="row" style="gap:12px"><span class="note">{devices.length} connected</span>
        {#if session.isAdmin}<div class="segs" role="group" aria-label="Whose"><button class="seg" class:on={!everyone} onclick={() => { everyone = false; load(); }}>Mine</button><button class="seg" class:on={everyone} onclick={() => { everyone = true; load(); }}>Everyone</button></div>{/if}
      </span>
    </div>
    {#if !tokens}<div class="empty">Loading…</div>
    {:else if !devices.length}<div class="empty">None yet.</div>
    {:else}
      {#each devices as d}
        <div class="dev">
          <span class="dvi"><Icon name={isWeb(d) ? 'sparkle' : 'laptop'} /></span>
          <span class="grow" style="display:flex;flex-direction:column;gap:3px">
            <span style="font-weight:500">{d.name}{#if everyone} <span class="note">· {d.user}</span>{/if}</span>
            <span class="note">Connected {ago(d.created_at)} · last used {d.last_used ? ago(d.last_used) : 'not yet'} · stays signed in until {when(d.expires_at)} unless unused</span>
          </span>
          <button class="btn sm danger" onclick={() => revoke(d)}>Disconnect</button>
        </div>
      {/each}
    {/if}
  </section>

  {/if}

  {#if syncers.length}
  <section class="card" id="sync">
    <div class="hd">
      <h2>{everyone ? 'Everyone’s computers that sync' : 'Computers that sync'}</h2>
      {#if !everyone && sync?.files}<a class="btn" href={`/files?path=${encodeURIComponent(home + '/projects')}`}><Icon name="folder" />{sync.files} synced {sync.files === 1 ? 'file' : 'files'}</a>{/if}
    </div>
    {#if !tokens}<div class="empty">Loading…</div>
    {:else if !syncers.length}<div class="empty">None yet.</div>
    {:else}
      {#each syncers as d}
        <div class="dev">
          <span class="dvi"><Icon name="refresh" /></span>
          <span class="grow" style="display:flex;flex-direction:column;gap:3px">
            <span style="font-weight:500">{d.name.replace(/^Sync on /, '')}{#if everyone} <span class="note">· {d.user}</span>{/if}</span>
            <span class="note">Linked {agoPhrase(d.created_at)} · last copied {d.last_used ? agoPhrase(d.last_used) : 'nothing yet'}</span>
          </span>
          <button class="btn sm danger" onclick={() => (stopping = d)}>Turn off</button>
        </div>
      {/each}
    {/if}
  </section>

  {/if}

  {#if personal.length}
  <section class="card">
    <div class="hd">
      <div style="display:flex;flex-direction:column;gap:4px"><h2>Personal tokens</h2><span class="note">For build servers and scripts that can't open a browser</span></div>
      <button class="btn" onclick={() => { form = { name: '', scope: 'write', folders: '', days: 30 }; dialog = 'new'; }}><Icon name="key" />New token</button>
    </div>
    {#if personal.length}
      <div class="scroll-x"><table class="table">
        <thead><tr><th>Name</th><th>Can</th><th>Limited to</th><th>Last used</th><th>Expires</th><th></th></tr></thead>
        <tbody>
          {#each personal as t}
            <tr>
              <td><span style="font-weight:500">{t.name}</span> <span class="mono note">…{t.hint}</span>{#if everyone}<div class="note">{t.user}</div>{/if}</td>
              <td><span class="tag {t.scope === 'read' ? 'blue' : 'green'}">{t.scope === 'read' ? 'Read' : 'Read and write'}</span></td>
              <td class="mono note">{t.folders?.join(', ') || 'Everything you can reach'}</td>
              <td class="muted">{t.last_used ? ago(t.last_used) : 'Never'}</td>
              <td class:warn={t.expires_in_days <= 7} title={when(t.expires_at)}>{t.expires_in_days <= 0 ? 'Today' : t.expires_in_days === 1 ? 'Tomorrow' : `${t.expires_in_days} days`}</td>
              <td style="text-align:right"><button class="btn sm danger" onclick={() => revoke(t)}>Revoke</button></td>
            </tr>
          {/each}
        </tbody>
      </table></div>
    {:else if tokens}<div class="empty">No personal tokens.</div>{/if}
  </section>
  {/if}
</div>

{#if dialog === 'new'}
  <Modal title="New personal token" onclose={() => (dialog = null)}>
    <form onsubmit={create} style="display:flex;flex-direction:column;gap:14px">
      <label class="lbl">Name<input class="field" bind:value={form.name} placeholder="e.g. nightly report job" required maxlength="128" /></label>
      <div class="row" style="gap:12px">
        <label class="lbl grow">Can<select class="field" bind:value={form.scope}><option value="write">Read and write</option><option value="read">Read only</option></select></label>
        <label class="lbl" style="width:140px">Days<input class="field" type="number" min="1" max="365" bind:value={form.days} /></label>
      </div>
      <label class="lbl">Only these folders (optional, one per line)<textarea class="field" rows="3" style="height:auto;padding:10px 12px;font-family:var(--mono)" bind:value={form.folders} placeholder={`/users/${session.user.username}/projects/reports`}></textarea></label>
      <div class="row" style="justify-content:flex-end"><button type="button" class="btn" onclick={() => (dialog = null)}>Cancel</button><button class="btn pri">Create token</button></div>
    </form>
  </Modal>
{/if}
{#if stopping}
  <Modal title={`Stop ${stopping.name.replace(/^Sync on /, '')} from syncing?`} onclose={() => (stopping = null)}>
    <p style="margin:0;font-size:13px;line-height:1.55;color:var(--text-2);overflow-wrap:anywhere">It stops copying new files at once. Files already copied stay where they are. To sync it again later, link it again from the computer.</p>
    <div class="row" style="justify-content:flex-end"><button class="btn" onclick={() => (stopping = null)}>Keep syncing</button><button class="btn danger" onclick={() => { const d = stopping; stopping = null; revoke(d); }}>Turn off</button></div>
  </Modal>
{/if}
{#if created}
  <Modal title="Copy your token now" onclose={() => (created = null)}>
    <p style="margin:0;font-size:13px;line-height:1.55;color:var(--text-2)">This is the only time it's shown. Store it in your build server's secret store.</p>
    <Copy text={created.token} label="token" />
    <p class="note" style="margin:0">Use it as <span class="mono">Authorization: Bearer …</span> against <span class="mono">{mcpUrl}</span> or the REST API.</p>
    <div class="row" style="justify-content:flex-end"><button class="btn pri" onclick={() => (created = null)}>Done</button></div>
  </Modal>
{/if}

<style>
  .desk { display: flex; align-items: center; gap: 16px; padding: 18px 22px; flex-wrap: wrap; }
  .di { width: 40px; height: 40px; border-radius: 11px; display: grid; place-items: center; background: var(--amber-bg); color: var(--amber); flex: none; }
  .desk-t { flex: 1; min-width: 220px; display: flex; flex-direction: column; gap: 2px; font-size: 14px; }
  .desk-t b { font-weight: 600; }
  .desk-t span { font-size: 13px; color: var(--text-2); }
  .desk-btn { height: 42px; padding: 0 18px; font-size: 14px; border-radius: 10px; }
  .hero { padding: 0; overflow: hidden; }
  .hero-main { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 28px; padding: 26px 28px; align-items: center; }
  .hero-copy { display: flex; flex-direction: column; gap: 18px; }
  .kind { display: inline-flex; align-items: center; gap: 9px; font-size: 13px; font-weight: 500; color: var(--text); }
  .kind :global(.ic) { color: var(--amber); }
  .kind .faint { color: var(--faint); font-weight: 400; }
  .steps3 { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 14px; }
  .steps3 li { display: flex; align-items: center; gap: 12px; font-size: 14px; color: var(--text-2); }
  .steps3 b { color: var(--text); font-weight: 500; }
  .steps3 .n { width: 24px; height: 24px; flex: none; border-radius: 50%; display: grid; place-items: center; font-size: 12px; font-weight: 600;
    color: var(--amber); background: var(--amber-bg); font-variant-numeric: tabular-nums; }
  .live { display: flex; align-items: center; gap: 10px; padding: 13px 28px; border-top: 1px solid var(--line); background: var(--bg-side); font-size: 13px; color: var(--text-2); }
  .live.ok { color: var(--text); }
  .live.ok :global(.ic) { color: var(--green); }
  .live b { font-weight: 500; }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--amber); flex: none; animation: pulse 1.6s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: .35; } }
  @media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
  @media (max-width: 820px) { .hero-main { grid-template-columns: minmax(0, 1fr); } }
  .apps { display: flex; align-items: center; gap: 14px; padding: 14px 18px; flex-wrap: wrap; }
  .ai { width: 34px; height: 34px; border-radius: 9px; display: grid; place-items: center; background: var(--raise); color: var(--amber); flex: none; }
  .apps-t { display: flex; flex-direction: column; gap: 1px; font-size: 13.5px; }
  .apps-t b { font-weight: 500; }
  .apps-t span { font-size: 12px; color: var(--faint); }
  .apps-how { flex: 1; min-width: 200px; font-size: 13px; color: var(--text-2); }
  .apps-how b { font-weight: 500; color: var(--text); }
  .apps-act { flex: 1 1 320px; min-width: 0; }
  .adv { padding: 16px 22px; }
  .adv summary { cursor: pointer; font-size: 13px; font-weight: 500; color: var(--text-2); }
  .adv-body { display: flex; flex-direction: column; gap: 22px; padding-top: 18px; }
  .adv-sec { display: flex; flex-direction: column; gap: 10px; }
  .adv-sec h3 { margin: 0; font-size: 13px; font-weight: 500; color: var(--text); }
  .adv-sec h3 .faint { color: var(--faint); font-weight: 400; margin-left: 6px; }
  .adv-sec p { margin: 0; }
  .adv-h { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  @media (max-width: 860px) { .web-body { grid-template-columns: 1fr; gap: 18px; } }
  .card > .empty { padding: 26px 22px; }
  .fp { margin: 0; padding: 0 24px 14px; background: var(--bg-side); font-size: 11.5px; color: var(--faint); }
  .fp .mono { letter-spacing: .02em; overflow-wrap: anywhere; }
  .hd { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 18px 22px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
  .dev { display: flex; align-items: center; gap: 14px; padding: 14px 22px; border-bottom: 1px solid var(--line-soft); font-size: 13px; }
  .dev:last-child { border-bottom: 0; }
  .dvi { width: 34px; height: 34px; border-radius: 9px; background: var(--raise); color: var(--text-2); display: grid; place-items: center; }
  .warn { color: var(--amber); }
  .where { display: grid; grid-template-columns: max-content 1fr; gap: 8px 18px; margin: 0; font-size: 13px; }
  .where dt { color: var(--text-2); }
  .where dd { margin: 0; overflow-wrap: anywhere; }
  .where dd.mono { font-size: 12.5px; }
  @media (max-width: 600px) { .where { grid-template-columns: 1fr; gap: 2px; } .where dd { margin-bottom: 8px; } }
</style>
