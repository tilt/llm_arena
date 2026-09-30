<script lang="ts">
  import type { CatalogItem } from "../lib/backend";
  import { joinRef, splitRef, thinkingLevels } from "../lib/presets";
  import { perMtok } from "../lib/format";

  // A model reference with its thinking setting ("ollama:qwen3:4b#reasoning=none"). Models that are not installed or
  // reachable right now stay selectable and are marked, so a saved choice never silently changes. The thinking
  // select offers only what the chosen model accepts. `empty` labels the "" choice (e.g. "Local small: qwen3:4b").
  let {
    value = $bindable(""), options, label, id, empty = "— choose —", onchange,
  }: { value?: string; options: CatalogItem[]; label: string; id: string; empty?: string; onchange?: (ref: string) => void } = $props();

  const parts = $derived(splitRef(value ?? ""));
  const item = $derived(options.find((o) => o.ref === parts.base));
  const levels = $derived(thinkingLevels(parts.base, item));
  const groups = $derived([...new Set(options.map((o) => o.source))]);
  const why = $derived(!parts.base ? "Choose a model first" : levels.length ? "How much the model thinks before answering"
    : item?.spec.provider === "lmstudio" ? "LM Studio does not take a thinking setting" : "This model does not think");
  function set(next: string) {
    value = next;
    onchange?.(next);
  }
  function setBase(base: string) {
    // Keep the thinking setting only where the new model accepts it.
    const keep = thinkingLevels(base, options.find((o) => o.ref === base)).some((t) => t.value === parts.reasoning);
    set(base ? joinRef(base, keep ? parts.reasoning : "", parts.rest) : "");
  }
</script>

<div class="ref">
  <select {id} aria-label={`${label}: model`} value={parts.base} onchange={(e) => setBase(e.currentTarget.value)}>
    <option value="">{empty}</option>
    {#if parts.base && !item}<option value={parts.base}>{parts.base} (not available right now)</option>{/if}
    {#each groups as group (group)}
      <optgroup label={group}>
        {#each options.filter((o) => o.source === group) as o (o.ref)}
          <option value={o.ref}>{o.ref.replace(`${group}:`, "")} · {perMtok(o.input_cost_per_mtok, o.output_cost_per_mtok)}</option>
        {/each}
      </optgroup>
    {/each}
  </select>
  <select aria-label={`${label}: thinking`} title={why} value={parts.reasoning}
    onchange={(e) => set(joinRef(parts.base, e.currentTarget.value, parts.rest))} disabled={!levels.length}>
    {#if levels.length}
      {#each levels as t (t.value)}<option value={t.value}>{t.label}</option>{/each}
    {:else}
      <option value="">{parts.base ? "no thinking setting" : "thinking"}</option>
    {/if}
  </select>
</div>

<style>
  .ref { display: grid; grid-template-columns: minmax(0, 1fr) 140px; gap: 6px; }
  .ref select { min-width: 0; width: 100%; }
  @media (max-width: 420px) { .ref { grid-template-columns: minmax(0, 1fr); } }
</style>
