<script lang="ts">
  import { heatInk, heatStep, type Matrix } from "../lib/report";

  let { matrix, format, label }: { matrix: Matrix; format: (v: number) => string; label: string } = $props();
</script>

<div class="wrap" role="table" aria-label={label}>
  <div class="row head" role="row" style:grid-template-columns={`minmax(120px, 180px) repeat(${matrix.columns.length}, minmax(64px, 1fr))`}>
    <span role="columnheader"></span>
    {#each matrix.columns as column (column)}<span role="columnheader" class="col">{column}</span>{/each}
  </div>
  {#each matrix.rows as row, i (row)}
    <div class="row" role="row" style:grid-template-columns={`minmax(120px, 180px) repeat(${matrix.columns.length}, minmax(64px, 1fr))`}>
      <span role="rowheader" class="rowlabel">{row}</span>
      {#each matrix.columns as column, j (column)}
        {@const value = matrix.values[i]?.[j] ?? null}
        {#if value === null}
          <span role="cell" class="cell empty" title={`${row} · ${column}: no data`}>–</span>
        {:else}
          <span role="cell" class="cell" title={`${row} · ${column}: ${format(value)}`}
            style:background={`var(--seq-${heatStep(value)})`} style:color={`var(${heatInk(heatStep(value))})`}>{format(value)}</span>
        {/if}
      {/each}
    </div>
  {/each}
</div>

<style>
  .wrap { overflow-x: auto; font-size: 13px; }
  .row { display: grid; gap: 2px; margin-bottom: 2px; }
  .head .col { color: var(--text-secondary); font-size: 12px; padding: 0 4px 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: center; }
  .rowlabel { color: var(--text-secondary); padding: 8px 8px 8px 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cell { display: flex; align-items: center; justify-content: center; min-height: 34px; border-radius: 3px; font-variant-numeric: tabular-nums; }
  .empty { color: var(--text-muted); background: transparent; border: 1px dashed var(--grid); }
</style>
