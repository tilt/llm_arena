<script lang="ts">
  import { app } from "../lib/app.svelte";
  import type { Leaderboard, LeaderboardEntry } from "../lib/contracts";
  import { num, pct, usd } from "../lib/format";
  import { go } from "../lib/router.svelte";

  let boards = $state<Leaderboard[]>([]);
  let loading = $state(true);
  let error = $state("");
  let scenario = $state("");
  let showLegacy = $state(false);

  $effect(() => {
    if (!app.backend) return;
    loading = true;
    app.backend.leaderboard().then(
      (result) => { boards = result; loading = false; },
      (e) => { error = e instanceof Error ? e.message : String(e); loading = false; },
    );
  });

  const scenarios = $derived([...new Set(boards.map((b) => b.scenario))]);
  const visible = $derived(
    boards.filter((b) => (!scenario || b.scenario === scenario) && (showLegacy || b.scenario_version !== "legacy")),
  );
  const legacyCount = $derived(boards.filter((b) => b.scenario_version === "legacy").length);

  type Role = { model?: string; provider?: string; reasoning_effort?: string | null; tool_mode?: string };
  function models(entry: LeaderboardEntry): string[] {
    const roles = (entry.setup.roles ?? {}) as Record<string, Role | string>;
    return Object.entries(roles).map(([role, spec]) => {
      if (typeof spec === "string") return `${role}: ${spec}`;
      const extras = [spec.reasoning_effort === "none" ? "no thinking" : spec.reasoning_effort, spec.tool_mode === "json" ? "json tools" : ""]
        .filter(Boolean).join(", ");
      return `${role}: ${spec.provider}:${spec.model}${extras ? ` (${extras})` : ""}`;
    });
  }
  function policy(entry: LeaderboardEntry): string {
    const d = entry.setup.decisions as { policy?: string; control?: string; ollaya_model?: string } | null | undefined;
    if (!d) return "agent decides";
    return `${d.policy === "ollaya" ? `ollaya ${d.ollaya_model ?? ""}` : d.policy} · ${d.control ?? "policy"}`;
  }
  const params = (entry: LeaderboardEntry) =>
    Object.entries((entry.setup.params ?? {}) as Record<string, unknown>).map(([k, v]) => `${k}=${String(v)}`).join(", ");
</script>

<h1>Leaderboard</h1>
<p class="lead">
  Every run pooled, per scenario. Trials count together only when they ran the same setup (models, call settings,
  parameters and control policy, whatever the config was named) on the same scenario version and task content. Each
  task weighs the same; the interval is a 95% bootstrap over tasks. The last column compares an entry with the leader on
  the tasks both ran (paired permutation test).
</p>

<div class="filters">
  <select bind:value={scenario} aria-label="Scenario">
    <option value="">All scenarios</option>
    {#each scenarios as s (s)}<option value={s}>{s}</option>{/each}
  </select>
  {#if legacyCount}
    <label class="inline"><input type="checkbox" bind:checked={showLegacy} /> Show runs from before fingerprints ({legacyCount})</label>
  {/if}
</div>

{#if loading}
  <p class="muted">Loading…</p>
{:else if error}
  <p class="note">{error}</p>
{:else if !visible.length}
  <p class="muted">No comparable runs yet. <a href="#/build" onclick={() => go("/build")}>Build an experiment</a>, run it, and it appears here.</p>
{/if}

{#each visible as board (`${board.scenario}@${board.scenario_version}`)}
  <h2>{board.scenario} <span class="pill">version {board.scenario_version}</span> <span class="muted small">{board.tasks} tasks</span></h2>
  {#if board.scenario_version === "legacy"}
    <p class="note">These runs predate setup fingerprints: entries only merge when name, models and parameters match, and the
      control policy is not recorded. Rerun for firm comparisons.</p>
  {/if}
  <div class="card table-wrap">
    <table>
      <thead><tr><th class="n">#</th><th>Config</th><th>Setup</th><th class="n">Pass rate [95% CI]</th><th class="n">Tasks</th>
        <th class="n">Trials</th><th class="n">Runs</th><th class="n">$/trial</th><th class="n">p50 s</th><th class="n">vs #1 (shared tasks)</th></tr></thead>
      <tbody>
        {#each board.entries as e (e.fingerprint)}
          <tr>
            <td class="n">{e.rank}</td>
            <td><strong>{e.config}</strong>{#if e.names.length > 1}<div class="muted small">also: {e.names.filter((n) => n !== e.config).join(", ")}</div>{/if}
              <div class="muted small mono" title="setup fingerprint">{e.fingerprint}</div></td>
            <td class="setup">
              <span class="pill">{policy(e)}</span>
              {#each models(e) as m (m)}<div class="small">{m}</div>{/each}
              {#if params(e)}<div class="muted small">{params(e)}</div>{/if}
            </td>
            <td class="n">
              <div>{pct(e.pass_rate)} <span class="muted">[{pct(e.ci_low)}–{pct(e.ci_high)}]</span></div>
              <div class="ci" aria-hidden="true"><span style={`left:${e.ci_low * 100}%;width:${(e.ci_high - e.ci_low) * 100}%`}></span><i style={`left:${e.pass_rate * 100}%`}></i></div>
            </td>
            <td class="n">{e.tasks}</td><td class="n">{e.trials}</td>
            <td class="n" title={e.runs.join("\n")}>{e.runs.length}</td>
            <td class="n">{usd(e.mean_cost_usd)}</td><td class="n">{num(e.latency_p50_s, 1)}</td>
            <td class="n">
              {#if e.delta_vs_leader === null || e.delta_vs_leader === undefined}{e.rank === 1 ? "leader" : "no shared tasks"}
              {:else}{e.delta_vs_leader > 0 ? "+" : ""}{pct(e.delta_vs_leader)} <span class="muted">p={num(e.p_vs_leader, 2)} ({e.shared_tasks})</span>{/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    {#if board.entries.some((e) => (e.shared_tasks ?? 20) < 20)}
      <p class="note">Some comparisons rest on fewer than 20 shared tasks: treat them as indicative only.</p>
    {/if}
  </div>
{/each}

<style>
  .filters { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 12px 0; }
  .inline { display: flex; gap: 6px; align-items: center; font-size: 13px; }
  .small { font-size: 12px; }
  .mono { font-family: ui-monospace, monospace; }
  .setup { min-width: 220px; }
  .ci { position: relative; height: 6px; background: var(--surface-2); border-radius: 3px; margin-top: 4px; min-width: 90px; }
  .ci span { position: absolute; top: 0; height: 6px; background: var(--accent); opacity: 0.35; border-radius: 3px; }
  .ci i { position: absolute; top: -2px; width: 2px; height: 10px; background: var(--accent); }
</style>
