<script lang="ts">
  import type { CatalogItem } from "../lib/backend";
  import { perMtok } from "../lib/format";

  // No fallback on `value`: it is bound to optional role slots that start out undefined.
  let {
    value = $bindable(), options, empty = "", label, onchange,
  }: { value?: string; options: CatalogItem[]; empty?: string; label: string; onchange?: (ref: string) => void } = $props();
  const groups = $derived([...new Set(options.map((o) => o.source))]);
</script>

<select bind:value aria-label={label} onchange={() => onchange?.(value ?? "")}>
  {#if empty}<option value="">{empty}</option>{/if}
  {#each groups as group (group)}
    <optgroup label={group}>
      {#each options.filter((o) => o.source === group) as o (o.ref)}
        <option value={o.ref}>{o.ref.replace(`${group}:`, "")} · {perMtok(o.input_cost_per_mtok, o.output_cost_per_mtok)}</option>
      {/each}
    </optgroup>
  {/each}
</select>
