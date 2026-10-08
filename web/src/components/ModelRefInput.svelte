<script lang="ts">
  import type { CatalogItem } from "../lib/backend";
  import { THINKING, isOverride, joinRef, overrideReasoning, splitRef, thinkingLevels, thinkingOverride } from "../lib/presets";
  import { perMtok } from "../lib/format";

  // A model reference with its thinking setting ("ollama:qwen3:4b#reasoning=none"). Models that are not installed or
  // reachable right now stay selectable and are marked, so a saved choice never silently changes. The thinking
  // select offers only what the chosen model accepts. `empty` labels the "" choice (e.g. "Local small: qwen3:4b").
  // With `inheritedValue` (the concrete reference behind that choice) the thinking of the inherited model can change
  // on its own: the value becomes a thinking override ("#reasoning=low") and the model keeps following the preset.
  // With `thinkingWithModel` the thinking select appears only once there is a model (no idle "thinking" placeholder).
  let {
    value = $bindable(""), options, label, id, empty = "— choose —", inheritedValue = "", onchange, thinkingWithModel = false,
  }: {
    value?: string; options: CatalogItem[]; label: string; id: string; empty?: string; inheritedValue?: string;
    onchange?: (ref: string) => void; thinkingWithModel?: boolean;
  } = $props();

  const parts = $derived(splitRef(value ?? ""));
  const inherited = $derived(splitRef(inheritedValue));
  const overriding = $derived(isOverride(value ?? ""));
  // The model that runs and its thinking, whether chosen here or inherited.
  const base = $derived(parts.base || inherited.base);
  const reasoning = $derived(parts.base ? parts.reasoning : overriding ? overrideReasoning(value) : inherited.reasoning);
  const item = $derived(options.find((o) => o.ref === base));
  const accepted = $derived(thinkingLevels(base, item));
  // A saved setting the model does not accept stays visible (and marked), like a model that is not available.
  const unsupported = $derived(!!reasoning && !accepted.some((t) => t.value === reasoning));
  const levels = $derived(unsupported
    ? [...(accepted.length ? accepted : THINKING.slice(0, 1)),
      { value: reasoning, label: `${THINKING.find((t) => t.value === reasoning)?.label ?? reasoning} (not supported)` }]
    : accepted);
  const levelLabel = (r: string) => THINKING.find((t) => t.value === r)?.label ?? r;
  const groups = $derived([...new Set(options.map((o) => o.source))]);
  const why = $derived(!base ? "Choose a model first"
    : unsupported ? "This model does not accept this thinking setting; choose another"
    : overriding ? `Changed for this step; the inherited setting is “${levelLabel(inherited.reasoning)}”`
    : levels.length ? "How much the model thinks before answering"
    : item?.spec.provider === "lmstudio" ? "LM Studio does not take a thinking setting" : "This model does not think");

  function set(next: string) {
    value = next;
    onchange?.(next);
  }
  function setBase(next: string) {
    // Back to the inherited model drops any change of its thinking; a chosen model keeps the thinking shown where it
    // accepts it.
    if (!next) { set(""); return; }
    const keep = thinkingLevels(next, options.find((o) => o.ref === next)).some((t) => t.value === reasoning);
    set(joinRef(next, keep ? reasoning : "", parts.base ? parts.rest : []));
  }
  function setReasoning(next: string) {
    if (parts.base) set(joinRef(parts.base, next, parts.rest));
    else if (inherited.base) set(next === inherited.reasoning ? "" : thinkingOverride(next));
  }
</script>

<div class="ref" class:solo={thinkingWithModel && !base}>
  <select {id} aria-label={`${label}: model`} value={parts.base} onchange={(e) => setBase(e.currentTarget.value)}>
    <option value="">{empty}</option>
    {#if parts.base && !options.some((o) => o.ref === parts.base)}<option value={parts.base}>{parts.base} (not available right now)</option>{/if}
    {#each groups as group (group)}
      <optgroup label={group}>
        {#each options.filter((o) => o.source === group) as o (o.ref)}
          <option value={o.ref}>{o.ref.replace(`${group}:`, "")} · {perMtok(o.input_cost_per_mtok, o.output_cost_per_mtok)}</option>
        {/each}
      </optgroup>
    {/each}
  </select>
  {#if !thinkingWithModel || base}
  <select aria-label={`${label}: thinking`} title={why} value={reasoning} class:changed={overriding} class:unsupported
    onchange={(e) => setReasoning(e.currentTarget.value)} disabled={!levels.length}>
    {#if levels.length}
      {#each levels as t (t.value)}<option value={t.value}>{t.label}</option>{/each}
    {:else}
      <option value="">{base ? "no thinking setting" : "thinking"}</option>
    {/if}
  </select>
  {/if}
</div>

<style>
  .ref { display: grid; grid-template-columns: minmax(0, 1fr) 140px; gap: 6px; }
  .ref.solo { grid-template-columns: minmax(0, 1fr); }
  .ref select { min-width: 0; width: 100%; }
  .ref select.changed { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
  .ref select.unsupported { border-color: var(--critical); }
  @media (max-width: 420px) { .ref { grid-template-columns: minmax(0, 1fr); } }
</style>
