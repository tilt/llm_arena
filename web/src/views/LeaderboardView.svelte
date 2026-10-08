<script lang="ts">
  import { tick } from "svelte";
  import SetupDetail from "../components/SetupDetail.svelte";
  import { app } from "../lib/app.svelte";
  import { emptyConfig } from "../lib/builder";
  import type { Leaderboard, LeaderboardEntry } from "../lib/contracts";
  import { handoff } from "../lib/draft.svelte";
  import { newest } from "../lib/latest";
  import { num, pct, usd } from "../lib/format";
  import { modelsOf, roleLines, scenarioSummaries, setupPolicy } from "../lib/leaderboard";
  import { go } from "../lib/router.svelte";
  import { activeRuns, refreshRuns } from "../lib/runs.svelte";
  import { configFromSetup } from "../lib/setups";

  // Leaderboards are per scenario: the start page lists scenarios with their leader; a scenario's board ranks its
  // setups, and every setup opens to its task-by-task results, each linking to the trial's step inspector.
  let { scenario = "", entry = "" }: { scenario?: string; entry?: string } = $props();

  let boards = $state<Leaderboard[] | null>(null);
  let error = $state("");
  let model = $state("");
  let showLegacy = $state(false);
  let version = $state("");

  let refreshError = $state("");
  let editing: { fingerprint: string; run: string; from: string } | null = $state(null);
  let editName = $state("");
  let editBusy = $state(false);
  let editError = $state("");
  let editInput = $state<HTMLInputElement | null>(null);
  const beginLoad = newest();

  // Also reloads after a rename; a failed reload keeps the board on screen and says so.
  async function loadLeaderboard() {
    if (!app.backend) return;
    const current = beginLoad();
    try {
      const loaded = await app.backend.leaderboard();
      if (!current()) return;
      boards = loaded;
      error = refreshError = "";
    } catch (e) {
      if (!current()) return;
      const message = e instanceof Error ? e.message : String(e);
      if (boards) refreshError = `The leaderboard could not be refreshed: ${message}`;
      else error = message;
    }
  }

  $effect(() => {
    void loadLeaderboard();
  });

  const titleOf = (id: string) => app.scenarios.find((s) => s.id === id)?.title ?? id;
  const current = $derived((boards ?? []).filter((b) => showLegacy || b.scenario_version !== "legacy"));
  const summaries = $derived(scenarioSummaries(current));
  // A single scenario with results: go straight to its board.
  $effect(() => {
    if (!scenario && boards && summaries.length === 1) go(`/leaderboard/${encodeURIComponent(summaries[0]!.scenario)}`);
  });
  const versions = $derived((boards ?? []).filter((b) => b.scenario === scenario).map((b) => b.scenario_version)
    .sort((a, b) => (a === "legacy" ? 1 : b === "legacy" ? -1 : b.localeCompare(a, undefined, { numeric: true }))));
  const board = $derived((boards ?? []).find((b) => b.scenario === scenario && b.scenario_version === (version || versions[0])));
  const allModels = $derived([...new Set((board?.entries ?? []).flatMap(modelsOf))].sort());
  const rows = $derived((board?.entries ?? []).filter((e) => !model || modelsOf(e).includes(model)));
  const manifest = $derived(app.scenarios.find((s) => s.id === scenario));
  const running = $derived(new Set(activeRuns().map((r) => r.run_id)));

  const open = (e: LeaderboardEntry) => go(`/leaderboard/${encodeURIComponent(scenario)}${entry === e.fingerprint ? "" : `/${e.fingerprint}`}`);
  const latestRun = (e: LeaderboardEntry) => e.runs.at(-1) ?? "";
  const runHref = (run: string) => `#/runs/${encodeURIComponent(run)}`;
  function use(e: LeaderboardEntry) {
    const { config, exact } = configFromSetup(scenario, e.config, e.setup, app.models?.aliases ?? {});
    handoff.setup = {
      scenario, config: { ...emptyConfig(0), ...config },
      note: exact ? `Loaded “${e.config}” from the leaderboard.` : `Loaded “${e.config}”; some call settings have no alias here, check the models.`,
    };
    go(`/scenarios/${encodeURIComponent(scenario)}/setup`);
  }
  async function startTitleEdit(e: LeaderboardEntry) {
    const run = latestRun(e);
    if (!run || running.has(run)) return;
    editing = { fingerprint: e.fingerprint, run, from: e.config };
    editName = e.config;
    editError = "";
    await tick();
    editInput?.focus();
    editInput?.select();
  }
  function cancelTitleEdit() {
    editing = null;
    editName = "";
    editBusy = false;
    editError = "";
  }
  async function saveTitleEdit(event: SubmitEvent) {
    event.preventDefault();
    if (!app.backend || !editing) return;
    const next = editName.trim();
    if (!next || next === editing.from) {
      cancelTitleEdit();
      return;
    }
    editBusy = true;
    editError = "";
    try {
      await app.backend.renameRun(editing.run, { configs: { [editing.from]: next } });
      cancelTitleEdit();
      await loadLeaderboard();
      void refreshRuns();
    } catch (e) {
      editError = e instanceof Error ? e.message : String(e);
      editBusy = false;
    }
  }
</script>

{#if refreshError}<p class="note" role="alert">{refreshError}</p>{/if}
{#if !scenario}
  <h1>Leaderboard</h1>
  <p class="lead">Results are ranked per scenario: a setup (models per step, parameters, control policy) only competes with
    setups of the same scenario, on the same tasks. Pick a scenario to see its ranking and to walk through any trial.</p>
  {#if (boards ?? []).some((b) => b.scenario_version === "legacy")}
    <label class="inline"><input type="checkbox" bind:checked={showLegacy} /> Include runs from before setups were fingerprinted</label>
  {/if}
  {#if error}<p class="note" role="alert">{error}</p>
  {:else if boards === null}<div class="cards">{#each [1, 2, 3] as i (i)}<div class="card skeleton"></div>{/each}</div>
  {:else if !summaries.length}
    <div class="card empty"><p><strong>No results yet.</strong> Open a scenario, choose models and run it; its leaderboard appears here.</p>
      <a class="button" href="#/">Browse scenarios</a></div>
  {:else}
    <div class="cards">
      {#each summaries as s (`${s.scenario}@${s.version}`)}
        <a class="card scenario" href={`#/leaderboard/${encodeURIComponent(s.scenario)}`}>
          <span class="head"><strong>{titleOf(s.scenario)}</strong>{#if s.legacy}<span class="pill">legacy</span>{/if}</span>
          <span class="leader">
            <span class="muted small">leader</span>
            <span class="leader-name">{s.leader.config}</span>
            <span class="rate">{pct(s.leader.pass_rate)} <span class="muted small">[{pct(s.leader.ci_low)}–{pct(s.leader.ci_high)}]</span></span>
            <span class="ci" aria-hidden="true"><span style={`left:${s.leader.ci_low * 100}%;width:${(s.leader.ci_high - s.leader.ci_low) * 100}%`}></span><i style={`left:${s.leader.pass_rate * 100}%`}></i></span>
          </span>
          <span class="muted small">{s.setups} setups · {s.runs} runs · {s.trials} trials</span>
        </a>
      {/each}
    </div>
  {/if}
{:else}
  <p class="crumbs"><a href="#/leaderboard">Leaderboard</a> / {titleOf(scenario)}</p>
  <h1>{titleOf(scenario)}</h1>
  <p class="lead">Setups ranked by pass rate on this scenario's tasks, discounted when few tasks back it (each task weighs
    the same; 95% interval over tasks); ties go to the setup with more partial credit. Open a setup to see which pass
    criteria hold it back, how each task went, and to walk through a trial step by step.</p>
  <div class="filters">
    {#if versions.length > 1}
      <label>Scenario version <select bind:value={version}>{#each versions as v (v)}<option value={v}>{v}</option>{/each}</select></label>
    {/if}
    {#if allModels.length > 1}
      <label>Uses model <select bind:value={model}><option value="">any</option>{#each allModels as m (m)}<option value={m}>{m}</option>{/each}</select></label>
    {/if}
    <a href={`#/scenarios/${encodeURIComponent(scenario)}/setup`}>Run a new setup →</a>
  </div>
  {#if boards === null}
    <div class="card skeleton"></div>
  {:else if !board}
    <div class="card empty"><p><strong>No results for this scenario yet.</strong></p>
      <a class="button" href={`#/scenarios/${encodeURIComponent(scenario)}/setup`}>Choose models and run it</a></div>
  {:else}
    {#if board.scenario_version === "legacy"}
      <p class="note">These runs predate setup fingerprints: entries merge only when name, models and parameters match. Rerun for firm comparisons.</p>
    {/if}
    <div class="card table-wrap">
      <table class="board">
        <thead><tr><th class="n">#</th><th>Setup</th><th>Models per step</th><th class="n">Pass rate [95% CI]</th>
          <th class="n" title="Share of the graded checks met, every pass criterion weighing the same; breaks ranking ties">Partial</th>
          <th class="n">Tasks · trials</th><th class="n">$/trial</th><th class="n">p50 s</th><th class="n">vs #1</th></tr></thead>
        <tbody>
          {#each rows as e (e.fingerprint)}
            {@const expanded = entry === e.fingerprint}
            {@const run = latestRun(e)}
            <tr class:expanded>
              <td class="n rank">{e.rank}</td>
              <td>
                <div class="setup-title" class:editing={editing?.fingerprint === e.fingerprint}>
                  <button class="toggle" aria-expanded={expanded} aria-controls={`detail-${e.fingerprint}`} onclick={() => open(e)}
                    aria-label={`${expanded ? "Collapse" : "Expand"} ${e.config}`}>
                    <span class="chev" aria-hidden="true">{expanded ? "▾" : "▸"}</span></button>
                  {#if editing?.fingerprint === e.fingerprint}
                    <form class="title-edit" onsubmit={saveTitleEdit}>
                      <label class="sr-only" for={`rename-${e.fingerprint}`}>Setup title</label>
                      <input id={`rename-${e.fingerprint}`} type="text" bind:value={editName} bind:this={editInput} required disabled={editBusy} />
                      <button class="icon ok" type="submit" aria-label="Save setup title" title="Save" disabled={editBusy || !editName.trim()}>✓</button>
                      <button class="icon" type="button" aria-label="Cancel rename" title="Cancel" onclick={cancelTitleEdit} disabled={editBusy}>×</button>
                    </form>
                  {:else}
                    <button class="setup-name" aria-expanded={expanded} aria-controls={`detail-${e.fingerprint}`} onclick={() => open(e)}
                      title={`${expanded ? "Collapse" : "Expand"} ${e.config}`}><strong>{e.config}</strong></button>
                    {#if run}<a class="icon" href={runHref(run)} aria-label={`Open run ${run}`} title={`Open run ${run}`}>↗</a>{/if}
                    <button class="icon" onclick={() => startTitleEdit(e)} aria-label={`Rename ${e.config}`} title="Rename setup title"
                      disabled={!run || running.has(run)}>✏</button>
                  {/if}
                </div>
                {#if editing?.fingerprint === e.fingerprint && editError}<div class="error small">{editError}</div>{/if}
                <div class="muted small">{setupPolicy(e)}</div>
                {#if e.runs.length > 1 && run}<div class="muted small">opens latest run <code>{run}</code></div>{/if}
              </td>
              <td class="small">{#each roleLines(e) as l (l.role)}<div><span class="muted">{l.role}</span> {l.model}</div>{/each}</td>
              <td class="n">
                <div>{pct(e.pass_rate)} <span class="muted">[{pct(e.ci_low)}–{pct(e.ci_high)}]</span></div>
                <div class="ci" aria-hidden="true"><span style={`left:${e.ci_low * 100}%;width:${(e.ci_high - e.ci_low) * 100}%`}></span><i style={`left:${e.pass_rate * 100}%`}></i></div>
              </td>
              <td class="n">{#if e.credit == null}<span class="muted" title="recorded before partial credit">—</span>{:else}{pct(e.credit)}{/if}</td>
              <td class="n">{e.tasks} · {e.trials}{#if e.tasks < 5}<div><span class="pill few" title="Fewer than 5 tasks: the pass rate says little; the ranking discounts it">few tasks</span></div>{/if}</td>
              <td class="n">{usd(e.mean_cost_usd)}</td>
              <td class="n">{num(e.latency_p50_s, 1)}</td>
              <td class="n">{#if e.rank === 1}<span class="muted">leader</span>
                {:else if e.delta_vs_leader == null}<span class="muted" title="no tasks in common with the leader">—</span>
                {:else}<span title={`on ${e.shared_tasks} shared tasks; paired permutation p = ${num(e.p_vs_leader, 3)}`}
                  class:fail={(e.p_vs_leader ?? 1) < 0.05}>{Math.round(e.delta_vs_leader * 100)} pts</span>
                  <div class="muted small">p={num(e.p_vs_leader, 2)}</div>{/if}</td>
            </tr>
            {#if expanded}
              <tr class="detail-row" id={`detail-${e.fingerprint}`}><td colspan="9"><SetupDetail entry={e} {manifest} onuse={() => use(e)} /></td></tr>
            {/if}
          {:else}
            <tr><td colspan="9" class="muted">No setup uses {model}. <button class="link" onclick={() => (model = "")}>Show all</button></td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if rows.some((e) => (e.shared_tasks ?? 20) < 20)}
      <p class="muted small">Some comparisons rest on fewer than 20 shared tasks; differences are marked red only when significant (p &lt; 0.05).</p>
    {/if}
  {/if}
{/if}

<style>
  .crumbs { font-size: 13px; color: var(--text-muted); margin: 0 0 6px; }
  .inline { display: flex; gap: 6px; align-items: center; font-size: 13px; margin-bottom: 12px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
  .scenario { display: grid; gap: 10px; text-decoration: none; color: inherit; transition: border-color 0.15s; }
  .scenario:hover, .scenario:focus-visible { border-color: var(--accent); }
  .head { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; font-size: 15px; }
  .leader { display: grid; gap: 2px; }
  .leader-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rate { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .skeleton { height: 150px; background: var(--surface-2); }
  .empty { display: grid; gap: 10px; justify-items: start; }
  .empty p { margin: 0; }
  .filters { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin: 0 0 12px; font-size: 13px; }
  .filters label { display: flex; gap: 6px; align-items: center; }
  .board td { vertical-align: top; }
  .rank { font-weight: 600; }
  .setup-title { display: flex; gap: 4px; align-items: center; min-width: 190px; }
  .setup-title.editing { align-items: start; }
  .toggle { width: 24px; height: 24px; display: inline-grid; place-items: center; flex: 0 0 24px; background: transparent; border-color: transparent;
    border-radius: 6px; padding: 0; color: var(--text-primary); cursor: pointer; text-align: left; font: inherit; }
  .toggle:hover:not(:disabled) { background: var(--surface-3); }
  .toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
  .chev { color: var(--text-muted); display: inline-block; width: 12px; }
  .setup-name { min-width: 0; padding: 2px 4px; background: transparent; border-color: transparent; color: var(--text-primary);
    text-align: left; overflow-wrap: anywhere; }
  .setup-name:hover:not(:disabled), .setup-name:focus-visible { background: transparent; color: var(--accent); text-decoration: underline; }
  .icon { width: 24px; height: 24px; display: inline-grid; place-items: center; flex: 0 0 24px; padding: 0; border-radius: 6px;
    text-decoration: none; color: var(--text-secondary); background: transparent; border: 1px solid transparent; line-height: 1; }
  .icon:hover:not(:disabled), a.icon:hover, .icon:focus-visible { background: var(--surface-3); border-color: var(--border); color: var(--text-primary); }
  .icon.ok { color: var(--good); }
  .title-edit { display: grid; grid-template-columns: minmax(130px, 1fr) 24px 24px; gap: 4px; align-items: center; min-width: 240px; }
  .title-edit input { width: 100%; padding: 4px 7px; }
  tr.expanded > td { background: var(--surface-2); }
  .detail-row > td { background: var(--surface-2); border-top: none; }
  .ci { position: relative; height: 6px; background: var(--surface-3); border-radius: 3px; margin-top: 4px; min-width: 90px; }
  .ci span { position: absolute; top: 0; height: 6px; background: var(--accent); opacity: 0.35; border-radius: 3px; }
  .ci i { position: absolute; top: -2px; width: 2px; height: 10px; background: var(--accent); }
  .few { font-size: 10.5px; color: var(--kind-decision); }
</style>
