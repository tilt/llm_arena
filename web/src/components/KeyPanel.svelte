<script lang="ts">
  import { app, refresh } from "../lib/app.svelte";

  const labels: Record<string, string> = { openai: "OpenAI", anthropic: "Anthropic", typesafe: "TypeSafe (Jev)", tavily: "Tavily (live search)" };
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
  <h3>API keys</h3>
  <p class="muted">
    {#if app.mode === "local"}
      Keys from <code>.env</code> are used automatically. A key entered here is held in the local server's memory for this
      session only and is never sent back to the page.
    {:else}
      Keys stay in this browser tab and are sent only to the provider's API (OpenAI, Anthropic). Use a project key with a
      spend limit, and set a spend limit on each run.
    {/if}
  </p>
  {#each Object.entries(app.runtime?.keys ?? {}) as [provider, source] (provider)}
    <div class="row">
      <span class="name">{labels[provider] ?? provider}</span>
      <span class="pill" class:on={source !== "missing"}>{source === "env" ? "from .env" : source === "session" ? "session" : "not set"}</span>
      <input type="password" autocomplete="off" placeholder="paste key" bind:value={drafts[provider]} aria-label={`${labels[provider] ?? provider} API key`} />
      <button onclick={() => save(provider)} disabled={!drafts[provider] || busy === provider}>Use</button>
      {#if source === "session"}<button onclick={() => clear(provider)}>Forget</button>{/if}
    </div>
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
