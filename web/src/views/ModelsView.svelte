<script lang="ts">
  import EndpointPanel from "../components/EndpointPanel.svelte";
  import KeyPanel from "../components/KeyPanel.svelte";
  import { app, refresh } from "../lib/app.svelte";
  import type { CatalogItem } from "../lib/backend";
  import { endpointHint, groupOf } from "../lib/endpoints";
  import { perMtok } from "../lib/format";

  const CAPS = ["tools", "vision", "reasoning"] as const;
  let needs = $state<string[]>([]);
  let source = $state("");
  let query = $state("");
  let refreshing = $state(false);

  const caps = (m: CatalogItem) => (m.spec.capabilities ?? {}) as Record<string, boolean | undefined>;
  const visible = $derived(
    (app.models?.models ?? []).filter((m) => (!source || groupOf(m) === source) && needs.every((n) => caps(m)[n])
      && (!query || m.ref.toLowerCase().includes(query.toLowerCase()))),
  );
  const sources = $derived([...new Set((app.models?.models ?? []).map(groupOf))]);

  async function reload() {
    refreshing = true;
    await refresh({ models: true });
    refreshing = false;
  }
  const toggle = (need: string) => (needs = needs.includes(need) ? needs.filter((n) => n !== need) : [...needs, need]);
</script>

<h1>Models</h1>
<p class="lead">
  {app.mode === "local" ? "Discovered from Ollama, LM Studio, the configured API providers and your endpoints." : "Remote models available with your keys and endpoints."}
  Use the reference in experiments. Models without native tool calling use a text-based JSON protocol automatically.
</p>

<KeyPanel />
<EndpointPanel />

<div class="filters">
  <input type="text" placeholder="Search" bind:value={query} aria-label="Search models" />
  <select bind:value={source} aria-label="Provider"><option value="">All providers</option>{#each sources as s (s)}<option>{s}</option>{/each}</select>
  {#each CAPS as cap (cap)}<button class="pill" class:on={needs.includes(cap)} onclick={() => toggle(cap)} aria-pressed={needs.includes(cap)}>{cap}</button>{/each}
  <button onclick={reload} disabled={refreshing}>{refreshing ? "Refreshing…" : "Refresh"}</button>
</div>

{#each Object.entries(app.models?.unavailable ?? {}) as [provider, reason] (provider)}
  <p class="note">{provider} unavailable: {reason} {endpointHint(reason, app.mode)}</p>
{/each}

<div class="card table-wrap">
  <table>
    <thead><tr><th>Reference</th><th>Params</th><th>Quant</th><th class="n">Context</th><th>Tools</th><th>Vision</th><th>Thinking</th><th>Loaded</th><th class="n">$ in / out per Mtok</th></tr></thead>
    <tbody>
      {#each visible as m (m.ref)}
        <tr>
          <td><code>{m.ref}</code></td>
          <td>{m.parameters ?? ""}</td><td>{m.quantization ?? ""}</td>
          <td class="n">{m.context_length ? m.context_length.toLocaleString("en-US") : ""}</td>
          <td>{caps(m).tools ? "✓" : "json"}</td><td>{caps(m).vision ? "✓" : ""}</td><td>{caps(m).reasoning ? "✓" : ""}</td>
          <td>{m.loaded ? "●" : ""}</td>
          <td class="n">{perMtok(m.input_cost_per_mtok, m.output_cost_per_mtok)}</td>
        </tr>
      {:else}
        <tr><td colspan="9" class="muted">No models match.</td></tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 16px 0 8px; }
  .filters .pill { border: 1px solid var(--border); cursor: pointer; font-size: 13px; padding: 4px 10px; }
  code { font-size: 12px; }
</style>
