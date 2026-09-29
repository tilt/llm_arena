<script lang="ts">
  import type { CatalogItem } from "../lib/backend";
  import { THINKING, joinRef, splitRef } from "../lib/presets";
  import { perMtok } from "../lib/format";

  // A model reference with its thinking setting ("ollama:qwen3:4b#reasoning=none"). Models that are not
  // installed or reachable right now stay selectable and are marked, so a profile never silently changes.
  let { value = $bindable(""), options, label, id }: { value: string; options: CatalogItem[]; label: string; id: string } = $props();

  const parts = $derived(splitRef(value));
  const known = $derived(options.some((o) => o.ref === parts.base));
  const groups = $derived([...new Set(options.map((o) => o.source))]);
  const setBase = (base: string) => (value = joinRef(base, parts.reasoning, parts.rest));
  const setThinking = (reasoning: string) => (value = joinRef(parts.base, reasoning, parts.rest));
</script>

<div class="ref">
  <select {id} aria-label={`${label}: model`} value={parts.base} onchange={(e) => setBase(e.currentTarget.value)}>
    <option value="">— choose —</option>
    {#if parts.base && !known}<option value={parts.base}>{parts.base} (not available right now)</option>{/if}
    {#each groups as group (group)}
      <optgroup label={group}>
        {#each options.filter((o) => o.source === group) as o (o.ref)}
          <option value={o.ref}>{o.ref.replace(`${group}:`, "")} · {perMtok(o.input_cost_per_mtok, o.output_cost_per_mtok)}</option>
        {/each}
      </optgroup>
    {/each}
  </select>
  <select aria-label={`${label}: thinking`} value={parts.reasoning} onchange={(e) => setThinking(e.currentTarget.value)} disabled={!parts.base}>
    {#each THINKING as t (t.value)}<option value={t.value}>{t.label}</option>{/each}
  </select>
</div>

<style>
  .ref { display: grid; grid-template-columns: minmax(0, 1fr) 130px; gap: 6px; }
  .ref select { min-width: 0; width: 100%; }
</style>
