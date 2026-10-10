<script lang="ts">
  import { app, refresh } from "../lib/app.svelte";
  import { keyRows } from "../lib/keys";

  // providers: only these rows (an inline panel asking for the one key a page needs); heading replaces the default.
  // onset: after a key is set (e.g. move focus back to the action that needed it).
  let { providers, heading, onset }: { providers?: string[]; heading?: string; onset?: (provider: string) => void } = $props();
  const rows = $derived(keyRows(app.runtime?.keys ?? {}, providers));
  const labels = $derived(Object.fromEntries(rows.map((r) => [r.provider, r.label])));
  let drafts = $state<Record<string, string>>({});
  let busy = $state("");
  let remember = $state(false);
  let message = $state("");

  async function save(provider: string) {
    if (!app.backend || !drafts[provider]) return;
    busy = provider;
    try {
      const persist = remember && app.canRememberKeys;
      await app.backend.setKey(provider, drafts[provider], persist);
      drafts[provider] = "";
      message = `${labels[provider] ?? provider} key set${persist ? " and remembered on this device" : " for this session"}.`;
      await refresh({ models: true });
      onset?.(provider);
    } catch (error) {
      message = error instanceof Error ? error.message : String(error);
    } finally {
      busy = "";
    }
  }

  async function clear(provider: string) {
    if (!app.backend) return;
    await app.backend.clearKey(provider);
    await refresh({ models: true });
  }
</script>

<div class="card keys">
  <h3>{heading ?? "API keys"}</h3>
  {#if !providers}
  <p class="muted">
    {#if app.mode === "local"}
      Keys from <code>.env</code> are used automatically. A key entered here is held in the local server's memory for this
      session only and is never sent back to the page.
    {:else}
      Keys stay in this browser tab and are sent only to the provider's API (OpenAI, Anthropic). Use a project key with a
      spend limit, and set a spend limit on each run.
    {/if}
  </p>
  {/if}
  {#each rows as row (row.provider)}
    <div class="row">
      <span class="name">{row.label}</span>
      <span class="pill" class:on={row.source !== "missing"}>{row.source === "env" ? "from .env" : row.source === "session" ? "session" : "not set"}</span>
      <input type="password" autocomplete="off" placeholder={row.placeholder} bind:value={drafts[row.provider]} aria-label={row.aria} />
      <button onclick={() => save(row.provider)} disabled={!drafts[row.provider] || busy === row.provider}>Use</button>
      {#if row.source === "session"}<button onclick={() => clear(row.provider)}>Forget</button>{/if}
    </div>
    {#if row.warning}<p class="muted small warning">{row.warning}</p>{/if}
  {/each}
  {#if app.mode === "browser" && app.canRememberKeys}
    <label class="remember"><input type="checkbox" bind:checked={remember} /> Remember keys on this device (stored
      unencrypted in this browser's local storage; leave off on shared computers)</label>
  {/if}
  {#if message}<p class="muted">{message}</p>{/if}
</div>

<style>
  .keys h3 { margin-top: 0; }
  .row { display: grid; grid-template-columns: 160px 90px minmax(120px, 1fr) auto auto; gap: 8px; align-items: center; margin: 6px 0; }
  @media (max-width: 640px) { .row { grid-template-columns: 1fr 1fr; } }
  .remember { display: block; margin-top: 8px; }
  code { background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
</style>
