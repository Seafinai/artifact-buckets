<script>
  import { api } from '../lib/api.js';
  import { session } from '../lib/session.svelte.js';
  import { toast, fail } from '../lib/toast.svelte.js';
  import { ago, agoPhrase, when } from '../lib/format.js';
  import Icon from '../lib/Icon.svelte';
  import Copy from '../lib/Copy.svelte';
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
</script>

<div class="page">
  <header class="page-head"><h1>Connect Claude</h1></header>

  <section class="card setup">
    <div class="kind"><Icon name="terminal" size={15} /><span>Claude Code</span><span class="faint">terminal, VS Code, JetBrains</span></div>
    <div class="ways">
      <div class="way">
        <h2>Ask Claude Code</h2>
        <Copy text={setup.prompt} label="the prompt" />
      </div>
      <div class="way">
        <div class="row" style="justify-content:space-between;gap:12px;flex-wrap:wrap">
          <h2>Or run one line</h2>
          <div class="segs" role="group" aria-label="Your computer">
            <button class="seg" class:on={os === 'windows'} onclick={() => (os = 'windows')}>Windows</button>
            <button class="seg" class:on={os === 'unix'} onclick={() => (os = 'unix')}>macOS and Linux</button>
          </div>
        </div>
        <Copy text={os === 'windows' ? setup.windows : setup.unix} label="the setup command" />
      </div>
    </div>
    <ol class="flow">
      <li><Icon name="terminal" size={15} /><span>Paste it {os === 'windows' ? 'into Claude Code or PowerShell' : 'into Claude Code or a terminal'}</span></li>
      <li><Icon name="check" size={15} /><span>Press <b>Connect</b> on the page that opens here</span></li>
      <li><Icon name="folder" size={15} /><span>Saves land in <span class="mono">{home}/projects</span></span></li>
    </ol>
    {#if setup.fingerprint}<p class="fp" title="The setup line checks the server's certificate against this before trusting it">Certificate SHA-256 <span class="mono">{setup.fingerprint.match(/.{1,4}/g).join(' ')}</span></p>{/if}
  </section>

  <section class="card web" id="web">
    <div class="kind"><Icon name="sparkle" size={15} /><span>Claude apps</span><span class="faint">web, desktop and mobile</span></div>
    {#if web.ready}
      <div class="web-body">
        <div class="web-copy">
          <h2>Add it as a connector</h2>
          <p class="note">Claude can then save what it makes into your folders, and open files from them, in any chat.</p>
          <Copy text={web.url} label="the connector address" />
        </div>
        <ol class="steps">
          <li><span class="n">1</span><span>In Claude, open <b>Settings</b>, then <b>Connectors</b>, and choose <b>Add custom connector</b></span></li>
          <li><span class="n">2</span><span>Name it <b>Artifact Buckets</b> and paste the address</span></li>
          <li><span class="n">3</span><span>Press <b>Connect</b> there, then <b>Connect</b> on the page that opens here</span></li>
        </ol>
      </div>
      <p class="web-foot">On a Team or Enterprise plan, an owner adds the connector once under <b>Organization settings</b>, then <b>Connectors</b>. Each person then connects with their own account.</p>
    {:else}
      <div class="web-body blocked">
        <span class="bi"><Icon name="lock" size={16} /></span>
        <div class="web-copy">
          {#if web.why === 'off'}
            <h2>Turned off on this server</h2>
            <p class="note">An admin can turn it back on by removing <span class="mono">AB_CLAUDE_WEB=false</span> from the server’s settings.</p>
          {:else}
            <h2>Needs a public address first</h2>
            <p class="note">Claude’s apps reach connectors from the internet, so this server needs a public https address with a trusted certificate.
              {#if web.why === 'self_signed'}<span class="mono">{host}</span> uses a self-signed certificate, which Claude won’t trust.
              {:else}<span class="mono">{host}</span> is only reachable on your own network.{/if}
              A Cloudflare Tunnel gives it one in a few minutes, with no ports to open.</p>
            {#if session.isAdmin}<a class="btn" href={guide} target="_blank" rel="noopener" style="align-self:flex-start"><Icon name="external" size={14} />Set up a public address</a>
            {:else}<p class="note" style="margin:0">Ask whoever runs Artifact Buckets to set one up.</p>{/if}
          {/if}
        </div>
      </div>
    {/if}
  </section>

  <details class="card alt" id="remove">
    <summary>Removing it from a computer</summary>
    <div class="rm">
      <p class="note">Takes the plugin, the sync and the certificate setting off that computer, and turns its connection off here. Files already saved stay in your folders.</p>
      <div class="segs os" role="group" aria-label="Your computer">
        <button class="seg" class:on={os === 'windows'} onclick={() => (os = 'windows')}>Windows</button>
        <button class="seg" class:on={os === 'unix'} onclick={() => (os = 'unix')}>macOS and Linux</button>
      </div>
      <Copy text={os === 'windows' ? setup.uninstall_windows : setup.uninstall_unix} label="the remove command" />
      <p class="note">Or ask Claude Code: <span class="mono">{setup.remove_prompt}</span></p>
    </div>
  </details>

  {#if session.isAdmin}
    <details class="card alt rollout" id="rollout">
      <summary>Set up every computer at once <span class="faint">Intune, Group Policy, Jamf</span></summary>
      <div class="ro-body">
        <div class="row" style="justify-content:space-between;gap:12px;flex-wrap:wrap">
          <span class="note">Claude Code installs the plugin at its next start; people sign in once when it asks.</span>
          <a class="btn sm" href="/claude/managed-settings.json" download="managed-settings.json"><Icon name="download" size={14} />Download</a>
        </div>
        <pre class="mono policy">{JSON.stringify(setup.managed_settings, null, 2)}</pre>
        <dl class="where">
          <dt>Windows</dt><dd class="mono">C:\Program Files\ClaudeCode\managed-settings.json</dd>
          <dt>Group Policy or Intune</dt><dd>The same JSON as the <span class="mono">Settings</span> value under <span class="mono">HKLM\SOFTWARE\Policies\ClaudeCode</span></dd>
          <dt>macOS</dt><dd class="mono">/Library/Application Support/ClaudeCode/managed-settings.json</dd>
          <dt>Linux</dt><dd class="mono">/etc/claude-code/managed-settings.json</dd>
        </dl>
        {#if setup.private_ca}<p class="note" style="margin:0">Computers must trust this server’s certificate first; domain-joined PCs already trust one from your own certificate authority.</p>{/if}
      </div>
    </details>
  {/if}

  <details class="card alt">
    <summary>Set it up by hand</summary>
    <div style="display:flex;flex-direction:column;gap:10px;padding-top:12px">
      <p class="note" style="margin:0">With the plugin (the connection, plus skills that teach Claude your folders):</p>
      <Copy text={`claude plugin marketplace add ${setup.marketplace}`} />
      <Copy text={`claude plugin install ${setup.plugin}`} />
      <p class="note" style="margin:6px 0 0">Or only the connection:</p>
      <Copy text={`claude mcp add --transport http artifact-buckets ${mcpUrl}`} />
      <p class="note" style="margin:0">Then sign in with <code>/mcp</code> in Claude Code, choose <b>artifact-buckets</b> and <b>Authenticate</b>.</p>
    </div>
  </details>

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
  .setup, .web { padding: 0; overflow: hidden; }
  .kind { display: flex; align-items: center; gap: 9px; padding: 12px 24px; border-bottom: 1px solid var(--line); font-size: 12.5px; font-weight: 500; color: var(--text-2); }
  .kind :global(.ic) { color: var(--amber); }
  .kind .faint { font-weight: 400; color: var(--faint); }
  .web-body { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); gap: 28px; padding: 22px 24px; align-items: start; }
  @media (max-width: 860px) { .web-body { grid-template-columns: 1fr; gap: 18px; } }
  .web-copy { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .web-copy h2 { margin: 0; }
  .web-copy .note { margin: 0; }
  .steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; font-size: 13px; line-height: 1.5; color: var(--text-2); }
  .steps li { display: flex; gap: 12px; align-items: flex-start; }
  .steps b { color: var(--text); font-weight: 500; }
  .steps .n { flex: none; width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; font-size: 11.5px; font-weight: 600; color: var(--amber); background: var(--amber-bg); border: 1px solid var(--amber-edge); }
  .web-foot { margin: 0; padding: 12px 24px; border-top: 1px solid var(--line); background: var(--bg-side); font-size: 12.5px; color: var(--muted); line-height: 1.55; }
  .web-foot b { color: var(--text-2); font-weight: 500; }
  .blocked { grid-template-columns: auto minmax(0, 1fr); gap: 16px; }
  .bi { width: 34px; height: 34px; border-radius: 9px; background: var(--raise); color: var(--text-2); display: grid; place-items: center; }
  .blocked .mono { font-size: 12px; color: var(--text-2); }
  .ways { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
  .way { padding: 22px 24px; display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .way > h2, .way > .row { min-height: 34px; display: flex; align-items: center; }
  .card > .empty { padding: 26px 22px; }
  .way + .way { border-left: 1px solid var(--line); }
  @media (max-width: 760px) { .way + .way { border-left: 0; border-top: 1px solid var(--line); } }
  .flow { list-style: none; margin: 0; padding: 14px 24px; display: flex; flex-wrap: wrap; gap: 10px 28px; border-top: 1px solid var(--line); background: var(--bg-side); font-size: 13px; color: var(--text-2); }
  .flow li { display: flex; align-items: center; gap: 9px; }
  .flow :global(.ic) { color: var(--amber); }
  .flow b { color: var(--text); font-weight: 500; }
  .fp { margin: 0; padding: 0 24px 14px; background: var(--bg-side); font-size: 11.5px; color: var(--faint); }
  .fp .mono { letter-spacing: .02em; overflow-wrap: anywhere; }
  .rollout summary .faint { font-weight: 400; margin-left: 8px; color: var(--faint); }
  .ro-body { padding-top: 16px; display: flex; flex-direction: column; gap: 16px; }
  .alt { padding: 16px 22px; }
  .alt summary { cursor: pointer; font-size: 13px; font-weight: 500; color: var(--text-2); }
  .hd { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 18px 22px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
  .dev { display: flex; align-items: center; gap: 14px; padding: 14px 22px; border-bottom: 1px solid var(--line-soft); font-size: 13px; }
  .dev:last-child { border-bottom: 0; }
  .dvi { width: 34px; height: 34px; border-radius: 9px; background: var(--raise); color: var(--text-2); display: grid; place-items: center; }
  .warn { color: var(--amber); }
  .rm { display: flex; flex-direction: column; gap: 12px; margin-top: 14px; }
  .rm p { margin: 0; }
  .rm .mono { overflow-wrap: anywhere; font-size: 12px; }
  .policy { margin: 0; padding: 14px 16px; border-radius: 10px; background: #0F1012; border: 1px solid var(--line); font-size: 12.5px; line-height: 1.55; color: var(--text); overflow-x: auto; }
  .where { display: grid; grid-template-columns: max-content 1fr; gap: 8px 18px; margin: 0; font-size: 13px; }
  .where dt { color: var(--text-2); }
  .where dd { margin: 0; overflow-wrap: anywhere; }
  .where dd.mono { font-size: 12.5px; }
  @media (max-width: 600px) { .where { grid-template-columns: 1fr; gap: 2px; } .where dd { margin-bottom: 8px; } }
</style>
