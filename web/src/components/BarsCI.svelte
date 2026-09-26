<script lang="ts">
  import { pct } from "../lib/format";
  import type { Bar } from "../lib/report";

  let { bars, label }: { bars: Bar[]; label: string } = $props();
  const clamp = (v: number) => (Number.isFinite(v) ? Math.min(1, Math.max(0, v)) * 100 : 0);
</script>

<div class="bars" role="list" aria-label={label}>
  {#each bars as bar (bar.label)}
    <div class="bar" role="listitem" title={`${bar.label}: ${pct(bar.value)} (95% CI ${pct(bar.low)}–${pct(bar.high)}, n=${bar.n})`}>
      <span class="label">{bar.label}</span>
      <span class="track">
        <span class="fill" style:width={`${clamp(bar.value)}%`}></span>
        <span class="ci" style:left={`${clamp(bar.low)}%`} style:width={`${Math.max(0, clamp(bar.high) - clamp(bar.low))}%`}></span>
      </span>
      <span class="value">{pct(bar.value)}</span>
    </div>
  {/each}
  <div class="axis"><span></span><span class="ticks"><span>0%</span><span>50%</span><span>100%</span></span><span></span></div>
</div>

<style>
  .bars { font-size: 13px; }
  .bar, .axis { display: grid; grid-template-columns: minmax(110px, 180px) 1fr 52px; gap: 10px; align-items: center; min-height: 30px; }
  .label { color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .track { position: relative; height: 20px; background: linear-gradient(to right, var(--grid) 1px, transparent 1px) 0 0 / 25% 100%; }
  .fill { position: absolute; left: 0; top: 3px; bottom: 3px; background: var(--accent); border-radius: 0 4px 4px 0; }
  .ci { position: absolute; top: 9px; height: 2px; background: var(--text-primary); opacity: 0.55; }
  .value { text-align: right; font-variant-numeric: tabular-nums; }
  .ticks { display: flex; justify-content: space-between; color: var(--text-muted); font-size: 11px; }
</style>
