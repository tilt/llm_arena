<script lang="ts">
  import { app } from "../lib/app.svelte";
  import { pct, usd } from "../lib/format";
  import { activeRuns, ago, elapsed, refreshRuns, runs } from "../lib/runs.svelte";
  import { WorkerBackend } from "../lib/worker-backend";

  // Running runs first (with live progress), then everything else newest first.
  let now = $state(Date.now());
  let stopping = $state<Set<string>>(new Set());
  let query = $state("");
  $effect(() => {
    const clock = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(clock);
  });
  $effect(() => { void refreshRuns(); });

  const running = $derived(activeRuns());
  const needle = $derived(query.trim().toLowerCase());
  const finished = $derived((runs.list ?? []).filter((r) => !r.active
    && (!needle || `${r.run_id} ${r.name} ${(r.scenarios ?? []).join(" ")}`.toLowerCase().includes(needle))));

  async function stop(runId: string) {
    stopping = new Set([...stopping, runId]);
    await app.backend?.cancel(runId);
    await refreshRuns();
  }
</script>

<h1>Runs</h1>
<p class="lead">Runs in progress first, then everything else, newest first. Open a run for its report and step inspector.</p>

{#if runs.error}<p class="note" role="alert">{runs.error}</p>{/if}

<section aria-labelledby="running-title" class="running-section">
  <h2 id="running-title">Running now {#if running.length}<span class="count">{running.length}</span>{/if}</h2>
  {#if runs.list === null}
    <div class="skeleton" aria-busy="true"></div>
  {:else if !running.length}
    <p class="muted empty">Nothing is running. <a href="#/build">Build an experiment</a> or open a scenario to run a setup.</p>
  {:else}
    <div class="live" aria-live="polite">
      {#each running as run (run.run_id)}
        {@const p = run.progress}
        {@const share = p && p.total ? p.done / p.total : 0}
        <article class="card live-run">
          <header>
            <span class="pulse" aria-hidden="true"></span>
            <a class="title" href={`#/runs/${encodeURIComponent(run.run_id)}`}>{run.name || run.run_id}</a>
            <span class="muted small">{(run.scenarios ?? []).join(", ")}</span>
          </header>
          <div class="bar" role="progressbar" aria-label={`${run.name}: ${p?.done ?? 0} of ${p?.total ?? "?"} trials finished`}
            aria-valuemin="0" aria-valuemax={p?.total ?? 0} aria-valuenow={p?.done ?? 0}>
            <span style:width={`${share * 100}%`}></span>
          </div>
          <p class="facts">
            <strong>{p?.done ?? 0} / {p?.total ?? "?"}</strong> trials
            · <span>{p?.running ?? 0} running</span> · <span>{p?.queued ?? 0} queued</span>
            {#if p?.done}· <span class="pass">{p.passed} passed</span>{#if p.errors} · <span class="fail">{p.errors} errors</span>{/if}{/if}
            · {usd(p?.spent_usd ?? 0)} · {elapsed(p?.started_at, now)}
          </p>
          <div class="actions">
            <a class="button primary" href={`#/runs/${encodeURIComponent(run.run_id)}`}>Follow live</a>
            <button onclick={() => stop(run.run_id)} disabled={stopping.has(run.run_id)}
              title="No new trials start; the ones running finish">{stopping.has(run.run_id) ? "Stopping…" : "Stop"}</button>
          </div>
        </article>
      {/each}
    </div>
  {/if}
</section>

<section aria-labelledby="recent-title">
  <div class="recent-head">
    <h2 id="recent-title">Recent runs</h2>
    <label class="search"><span class="sr-only">Filter runs</span>
      <input type="search" placeholder="Filter by name, id or scenario…" bind:value={query} /></label>
  </div>
  {#if app.backend instanceof WorkerBackend}
    <p class="muted small">Runs are kept in this browser. Import a run bundle (exported here or from the local app):
      <input type="file" accept="application/json,.json" onchange={async (e) => {
        const file = e.currentTarget.files?.[0];
        if (file && app.backend instanceof WorkerBackend) { await app.backend.importBundle(file); await refreshRuns(); }
      }} /></p>
  {/if}
  <div class="card table-wrap">
    <table>
      <thead><tr><th>Run</th><th>Scenarios</th><th>Started</th><th class="n">Trials</th><th class="n">Pass rate</th><th class="n">Errors</th></tr></thead>
      <tbody>
        {#each finished as run (run.run_id)}
          <tr>
            <td><a href={`#/runs/${encodeURIComponent(run.run_id)}`}><strong>{run.name || run.run_id}</strong></a>
              {#if run.name && run.name !== run.run_id}<div class="muted small mono">{run.run_id}</div>{/if}</td>
            <td class="small">{(run.scenarios ?? []).join(", ")}</td>
            <td class="muted" title={run.created_at}>{ago(run.created_at, now)}</td>
            <td class="n">{run.trials}</td><td class="n">{pct(run.trials ? run.passed / run.trials : null)}</td>
            <td class="n">{#if run.errors}<span class="fail">{run.errors}</span>{:else}0{/if}</td>
          </tr>
        {:else}
          <tr><td colspan="6" class="muted">{runs.list === null ? "Loading…" : needle ? "No run matches the filter." : "No finished runs yet."}</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

<style>
  h2 { display: flex; align-items: center; gap: 8px; }
  .count { font-size: 12px; font-weight: 600; color: var(--accent-ink); background: var(--accent); border-radius: 999px; padding: 1px 8px; }
  .running-section { margin-bottom: 8px; }
  .empty { margin: 0; }
  .live { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 12px; }
  @media (max-width: 520px) { .live { grid-template-columns: minmax(0, 1fr); } }
  .live-run { display: grid; gap: 10px; border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
  .live-run header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
  .title { font-weight: 600; font-size: 15px; color: var(--text-primary); text-decoration: none; }
  .title:hover { text-decoration: underline; }
  .pulse { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); align-self: center; animation: pulse 1.6s ease-in-out infinite; }
  @keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 60%, transparent); } 50% { box-shadow: 0 0 0 6px transparent; } }
  @media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
  .bar { height: 8px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
  .bar span { display: block; height: 100%; background: var(--accent); transition: width 0.4s ease; }
  .facts { margin: 0; font-size: 13px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
  .actions { display: flex; gap: 8px; }
  .recent-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .search input { min-width: 240px; }
  .mono { font-family: ui-monospace, monospace; }
  .skeleton { height: 120px; border-radius: var(--radius); background: var(--surface-2); }
</style>
