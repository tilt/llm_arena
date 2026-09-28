<script lang="ts">
  import type { Expectation } from "../lib/contracts";
  import CodeBlock from "./CodeBlock.svelte";

  // One piece of a task's ground truth, rendered by its format.
  let { expectation }: { expectation: Expectation } = $props();
  const value = $derived(expectation.value as unknown);
  const rows = $derived(Array.isArray(value) ? (value as unknown[][]) : []);
</script>

<div class="expectation">
  <h5>{expectation.label}</h5>
  {#if expectation.format === "code"}
    <CodeBlock text={String(value)} label={expectation.language ?? "code"} language={expectation.language ?? ""} max={260} />
  {:else if expectation.format === "list"}
    <ul>{#each value as unknown[] as item, i (i)}<li>{String(item)}</li>{/each}</ul>
  {:else if expectation.format === "table"}
    <div class="table-wrap"><table>
      <tbody>{#each rows as row, i (i)}<tr>{#each row as cell, j (j)}<td>{String(cell)}</td>{/each}</tr>{/each}</tbody>
    </table></div>
  {:else if expectation.format === "json"}
    <CodeBlock text={JSON.stringify(value, null, 2)} label="json" max={260} />
  {:else}
    <p>{String(value)}</p>
  {/if}
</div>

<style>
  .expectation { display: grid; gap: 4px; }
  h5 { margin: 0; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); font-weight: 600; }
  ul { margin: 0; padding-left: 18px; }
  p { margin: 0; }
  table { width: auto; }
  td { font-variant-numeric: tabular-nums; }
</style>
