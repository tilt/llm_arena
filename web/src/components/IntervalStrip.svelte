<script lang="ts">
  // A row's pass rate as a strip (design 7A): the band is the interval, the tick the rate, the heavier notch its
  // low end, which is what rows are ranked by. Purely visual: the text next to it carries the meaning.
  let { low, rate, high, width = 140 }: { low: number; rate: number; high: number; width?: number } = $props();
  const x = (v: number) => Math.max(0, Math.min(1, v)) * width;
</script>

<svg class="strip" {width} height="12" viewBox={`0 0 ${width} 12`} aria-hidden="true">
  <rect class="track" x="0" y="5" {width} height="2" />
  <rect class="band" x={x(low)} y="2" width={Math.max(2, x(high) - x(low))} height="8" />
  <rect class="tick" x={x(rate) - 1} y="1" width="2" height="10" />
  <rect class="notch" x={x(low) - 1} y="0" width="2" height="12" />
</svg>

<style>
  .strip { display: inline-block; vertical-align: middle; flex: none; }
  .track { fill: var(--grid); }
  .band { fill: var(--seq-1); }
  .tick { fill: var(--seq-5); }
  .notch { fill: var(--text-primary); }
</style>
