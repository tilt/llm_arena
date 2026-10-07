<script lang="ts">
  import type { ReplacementEffect } from "../lib/contracts";
  import { num, pct, usd } from "../lib/format";

  // Replacement study results for one scenario: rows are the swapped steps (roles), columns the candidate models.
  // A cell is coloured only when the difference is significant on the shared tasks (paired permutation, p < 0.05).
  let { effects }: { effects: ReplacementEffect[] } = $props();

  const roles = $derived([...new Set(effects.map((e) => e.role))]);
  const candidates = $derived([...new Set(effects.map((e) => e.candidate))]);
  const cell = (role: string, candidate: string) => effects.find((e) => e.role === role && e.candidate === candidate);
  const baseline = $derived(effects[0]?.baseline_rate);
  const points = (delta: number) => `${delta > 0 ? "+" : ""}${Math.round(delta * 100)} pts`;
  const short = (ref: string) => ref.replace(/^[a-z_]+:/, "").replace("#reasoning=none", " · no thinking").replace("#reasoning=", " · ");
</script>

<p class="muted small">Baseline pass rate {pct(baseline)} · each cell: change when only that step uses the column's model.</p>
<div class="card table-wrap">
  <table class="matrix">
    <thead>
      <tr><th scope="col">Step (role)</th>{#each candidates as c (c)}<th scope="col" class="n">{short(c)}</th>{/each}</tr>
    </thead>
    <tbody>
      {#each roles as role (role)}
        <tr>
          <th scope="row">{role}</th>
          {#each candidates as candidate (candidate)}
            {@const e = cell(role, candidate)}
            <td class="n">
              {#if e && (e.errors ?? 0) >= e.tasks && e.tasks > 0}
                <div class="fail small" title="Every compared trial errored (e.g. provider quota or a missing model)">not measurable</div>
                <div class="muted small">{e.errors} errored trials: check the run's errors</div>
              {:else if e}
                {@const significant = e.p_value < 0.05}
                <div class="delta" class:up={significant && e.delta > 0} class:down={significant && e.delta < 0}
                  title={`${pct(e.baseline_rate)} → ${pct(e.variant_rate)} on ${e.tasks} shared tasks; p = ${num(e.p_value, 3)}`}>
                  {points(e.delta)}{#if significant} <span class="sig">{e.delta > 0 ? "▲" : "▼"}</span>{/if}
                </div>
                <div class="muted small">p={num(e.p_value, 2)} · {e.tasks} tasks</div>
                {#if e.errors}<div class="fail small">{e.errors} errored trials count as fails</div>{/if}
                <div class="muted small">{e.delta_cost_usd >= 0 ? "+" : ""}{usd(e.delta_cost_usd)} · {e.delta_latency_s >= 0 ? "+" : ""}{num(e.delta_latency_s, 1)} s</div>
              {:else}
                <span class="muted" title="Not run: the baseline already uses this model for this step">—</span>
              {/if}
            </td>
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>
{#if effects.some((e) => e.tasks < 20)}
  <p class="note small">Fewer than 20 shared tasks: only large differences can be significant. Add tasks or repeats.</p>
{/if}

<style>
  .matrix th[scope="row"] { font-weight: 600; }
  .delta { font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .delta.up { color: var(--good); }
  .delta.down { color: var(--critical); }
  .sig { font-size: 11px; }
</style>
