<script>
  // One button that copies the Claude Code setup message. The message itself (server address, and for a server
  // with its own certificate the fingerprint the setup checks) stays out of the way until someone asks to see it,
  // and is shown here only when the browser won't let us copy (the Connect page lists it under Advanced).
  import Icon from './Icon.svelte';
  import Copy from './Copy.svelte';
  let { text } = $props();
  let done = $state(false);
  let show = $state(false);
  async function copy() {
    try { await navigator.clipboard.writeText(text); done = true; setTimeout(() => (done = false), 2500); }
    catch { show = true; }
  }
</script>

<div class="sc">
  <div class="row-main">
    <button class="btn pri big" onclick={copy}><Icon name={done ? 'check' : 'copy'} />{done ? 'Copied' : 'Copy setup for Claude Code'}</button>
    {#if done}<span class="hint">Now paste it into Claude Code.</span>{/if}
  </div>
  {#if show}<Copy text={text} label="the setup message" />{/if}
</div>

<style>
  .sc { display: flex; flex-direction: column; gap: 10px; align-items: flex-start; }
  .row-main { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  .big { height: 42px; padding: 0 18px; font-size: 14px; border-radius: 10px; }
  .hint { font-size: 13px; color: var(--text-2); }
  .sc :global(.cp) { align-self: stretch; }
</style>
