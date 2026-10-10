<script lang="ts">
  import type { ReplacementEffect } from "../lib/contracts";
  import { NOT_PRICED, num, pct, usd } from "../lib/format";

  // Effects against the baseline for one scenario, per baseline (with variants, each variant has its own). Swaps
  // (one step to one candidate) form a matrix: rows the swapped steps, columns the candidate models. Setups that change
  // something else are listed by name. A delta is coloured only when significant on the shared tasks (paired
  // permutation, p < 0.05).
  let { effects }: { effects: ReplacementEffect[] } = $props();

  const groups = $derived([...new Set(effects.map((e) => e.baseline ?? ""))].map((baseline) => {
    const members = effects.filter((e) => (e.baseline ?? "") === baseline);
    const swaps = members.filter((e) => e.role && e.candidate);
    return {
      baseline, rate: members[0]?.baseline_rate, swaps, others: members.filter((e) => !(e.role && e.candidate)),
      roles: [...new Set(swaps.map((e) => e.role))], candidates: [...new Set(swaps.map((e) => e.candidate))],
    };
  }));
  const points = (delta: number) => `${delta > 0 ? "+" : ""}${Math.round(delta * 100)} pts`;
  const short = (ref: string) => ref.replace(/^[a-z_]+:/, "").replace("#reasoning=none", " · no thinking").replace("#reasoning=", " · ");
</script>

{#snippet effect(e: ReplacementEffect)}
  {#if (e.errors ?? 0) >= e.tasks && e.tasks > 0}
    <div class="fail small" title="Every compared trial errored (e.g. provider quota or a missing model)">not measurable</div>
    <div class="muted small">{e.errors} errored trials: check the run's errors</div>
  {:else}
    {@const significant = e.p_value < 0.05}
    <div class="delta" class:up={significant && e.delta > 0} class:down={significant && e.delta < 0}
      title={`${pct(e.baseline_rate)} → ${pct(e.variant_rate)} on ${e.tasks} shared tasks; p = ${num(e.p_value, 3)}`}>
      {points(e.delta)}{#if significant} <span class="sig">{e.delta > 0 ? "▲" : "▼"}</span>{/if}
    </div>
    <div class="muted small">p={num(e.p_value, 2)} · {e.tasks} tasks</div>
    {#if e.errors}<div class="fail small">{e.errors} errored trials count as fails</div>{/if}
    <div class="muted small">{#if e.unpriced}cost: {NOT_PRICED}{:else}{e.delta_cost_usd >= 0 ? "+" : ""}{usd(e.delta_cost_usd)}{/if} · {e.delta_latency_s >= 0 ? "+" : ""}{num(e.delta_latency_s, 1)} s</div>
  {/if}
{/snippet}

{#each groups as g (g.baseline)}
  <p class="muted small">Baseline {#if g.baseline}<strong>{g.baseline}</strong>{/if} pass rate {pct(g.rate)}{g.swaps.length ? " · each cell: change when only that step uses the column's model" : ""}.</p>
  {#if g.swaps.length}
    <div class="card table-wrap">
      <table class="matrix">
        <thead>
          <tr><th scope="col">Step (role)</th>{#each g.candidates as c (c)}<th scope="col" class="n">{short(c)}</th>{/each}</tr>
        </thead>
        <tbody>
          {#each g.roles as role (role)}
            <tr>
              <th scope="row">{role}</th>
              {#each g.candidates as candidate (candidate)}
                {@const e = g.swaps.find((x) => x.role === role && x.candidate === candidate)}
                <td class="n">
                  {#if e}{@render effect(e)}{:else}<span class="muted" title="Not run: the baseline already uses this model for this step, or the model cannot do it">—</span>{/if}
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
  {#if g.others.length}
    <div class="card table-wrap">
      <table class="matrix">
        <thead><tr><th scope="col">Setup</th><th scope="col" class="n">Against the baseline</th></tr></thead>
        <tbody>
          {#each g.others as e (e.config)}<tr><th scope="row">{e.config}</th><td class="n">{@render effect(e)}</td></tr>{/each}
        </tbody>
      </table>
    </div>
  {/if}
{/each}
{#if effects.some((e) => e.tasks < 20)}
  <p class="note small">Fewer than 20 shared tasks: only large differences can be significant. Add tasks or repeats.</p>
{/if}

<style>
  .matrix th[scope="row"] { font-weight: 600; }
  .delta { font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .delta.up { color: var(--good); }
  .delta.down { color: var(--critical); }
  .sig { font-size: 11px; }
  .table-wrap + .table-wrap { margin-top: 8px; }
</style>
