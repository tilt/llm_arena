<script lang="ts">
  import ScenarioSetup from "../components/ScenarioSetup.svelte";
  import Tabs from "../components/Tabs.svelte";
  import TaskList from "../components/TaskList.svelte";
  import WorkflowDiagram from "../components/WorkflowDiagram.svelte";
  import { app } from "../lib/app.svelte";
  import { EVALUATION_PAGES, emptyConfig, toExperiment, validate, type BuilderState, type ConfigDraft } from "../lib/builder";
  import type { Estimate, LeaderboardEntry } from "../lib/contracts";
  import { addToDraft } from "../lib/draft.svelte";
  import { num, pct, usd } from "../lib/format";
  import { go } from "../lib/router.svelte";
  import { activeBaseline } from "../lib/baselines";
  import { configFromSetup } from "../lib/setups";
  import { CONTROL_PARAM, REVIEW_PARAM, resolve } from "../lib/workflow";

  let { id, tab = "overview" }: { id: string; tab?: string } = $props();
  const manifest = $derived(app.scenarios.find((s) => s.id === id));
  const TABS = ["overview", "tasks", "setup", "results"] as const;
  const active = $derived((TABS as readonly string[]).includes(tab) ? tab : "overview");
  const tabs = $derived([
    { key: "overview", label: "Overview" },
    { key: "tasks", label: "Tasks", count: manifest?.tasks },
    { key: "setup", label: "Workflow & models" },
    { key: "results", label: "Results" },
  ]);
  const show = (key: string) => go(`/scenarios/${encodeURIComponent(id)}/${key}`);

  let config = $state<ConfigDraft>({ ...emptyConfig(0), name: "my-setup", baseline: activeBaseline() });
  let limit = $state<number | null>(3);
  let repeats = $state(1);
  let split = $state<"all" | "dev" | "test">("all");
  let maxCostUsd = $state<number | null>(1);
  let onlyTask = $state("");
  let estimate = $state<Estimate | null>(null);
  let message = $state("");
  let busy = $state(false);
  let board = $state<LeaderboardEntry[] | null>(null);

  $effect(() => {
    if (!app.backend || active !== "results" || board) return;
    app.backend.leaderboard().then((boards) => {
      board = boards.filter((b) => b.scenario === id && b.scenario_version !== "legacy").flatMap((b) => b.entries).slice(0, 10);
    }, () => (board = []));
  });

  const preview = $derived(manifest?.workflow ? resolve(manifest.workflow, {
    ...Object.fromEntries(manifest.params.map((p) => [p.name, p.default])), [CONTROL_PARAM]: "agent", [REVIEW_PARAM]: true,
  }) : null);
  const plan = $derived<BuilderState>({
    name: `${id}-${config.name}`.replace(/[^\w.-]+/g, "-"), scenarios: [id], configs: [config], repeats,
    limit: onlyTask ? null : limit, judge: "", arena: false, maxCostUsd, split: onlyTask ? "all" : split,
  });
  const experiment = () => ({ ...toExperiment(plan, app.scenarios, app.baselines), ...(onlyTask ? { task_ids: [onlyTask] } : {}) });
  const errors = $derived(manifest ? validate(plan, app.scenarios, app.runtime?.sandbox ?? false,
    Object.fromEntries(Object.entries(app.runtime?.decision_services ?? {}).map(([k, v]) => [k, v?.status ?? ""]))) : []);
  const blocked = $derived((manifest?.requires ?? []).includes("sandbox") && !app.runtime?.sandbox);

  async function runEstimate() {
    if (!app.backend) return;
    busy = true; message = "";
    try { estimate = await app.backend.estimate(experiment()); }
    catch (e) { message = e instanceof Error ? e.message : String(e); }
    finally { busy = false; }
  }
  async function start() {
    if (!app.backend) return;
    busy = true; message = "";
    try {
      const runId = await app.backend.startRun({ experiment: experiment(), live: false });
      go(`/runs/${encodeURIComponent(runId)}`);
    } catch (e) { message = e instanceof Error ? e.message : String(e); busy = false; }
  }
  function addToExperiment() {
    addToDraft(id, $state.snapshot(config) as ConfigDraft);
    go("/build");
  }
  function runTask(taskId: string) {
    onlyTask = taskId;
    estimate = null;
    show("setup");
  }
  function useSetup(entry: LeaderboardEntry) {
    const { config: loaded, exact } = configFromSetup(id, entry.config, entry.setup, app.models?.aliases ?? {});
    config = loaded;
    message = exact ? `Loaded the setup of "${entry.config}".`
      : `Loaded "${entry.config}". Some call settings (e.g. thinking off) have no model alias here; check the models.`;
    show("setup");
  }
  const models = (entry: LeaderboardEntry) =>
    Object.entries((entry.setup.roles ?? {}) as Record<string, { model?: string; reasoning_effort?: string | null } | string>)
      .map(([role, s]) => `${role}: ${typeof s === "string" ? s : `${s.model}${s.reasoning_effort === "none" ? " (no thinking)" : ""}`}`);
</script>

{#if !manifest}
  <p class="muted">Unknown scenario <code>{id}</code>. <a href="#/">All scenarios</a></p>
{:else}
  <p class="crumbs"><a href="#/">Scenarios</a> / {manifest.kind === "benchmark" ? "Benchmarks" : "Agentic patterns"}</p>
  <h1>{manifest.title} <span class="pill">{manifest.pattern}</span></h1>
  <p class="lead">{manifest.brief?.summary ?? manifest.description}</p>

  <Tabs {tabs} active={active} id="scenario" onselect={show} />

  <div id="scenario-panel" role="tabpanel" aria-labelledby={`scenario-tab-${active}`} tabindex="-1">
    {#if active === "overview"}
      <div class="overview">
        <div class="facts">
          {#if manifest.brief}
            <section><h3>What the agent works with</h3><p>{manifest.brief.environment}</p></section>
            <section><h3>A task passes when</h3>
              <dl>{#each Object.entries(manifest.brief.criteria) as [name, meaning] (name)}<dt>{name}</dt><dd>{meaning}</dd>{/each}</dl>
            </section>
            {#if manifest.brief.measured?.length}<section><h3>Also measured</h3><ul>{#each manifest.brief.measured as m (m)}<li>{m}</li>{/each}</ul></section>{/if}
            {#if manifest.brief.traps?.length}<section><h3>What makes it hard</h3><ul>{#each manifest.brief.traps as t (t)}<li>{t}</li>{/each}</ul></section>{/if}
            {#if manifest.brief.compare?.length}<section><h3>Worth comparing</h3><ul>{#each manifest.brief.compare as c (c)}<li>{c}</li>{/each}</ul></section>{/if}
          {:else}
            <p>{manifest.description}</p>
          {/if}
          <p class="muted small">{manifest.tasks} tasks · version {manifest.version}{#if blocked} · needs a code sandbox (local app){/if}
            {#each (manifest.wiki ?? []).filter((l) => !EVALUATION_PAGES.has(l.title)) as link (link.url)} · <a href={link.url} target="_blank" rel="noopener">{link.title}</a>{/each}</p>
          <div class="actions">
            <button class="primary" onclick={() => show("setup")}>Choose models and run →</button>
            <button onclick={() => show("tasks")}>See the {manifest.tasks} tasks</button>
          </div>
        </div>
        {#if preview}
          <div class="card preview">
            <h3>Workflow <span class="muted small">with default settings</span></h3>
            <WorkflowDiagram flow={preview} label={`${manifest.title} workflow`} />
          </div>
        {/if}
      </div>
    {:else if active === "tasks"}
      <TaskList scenario={id} onrun={runTask} />
    {:else if active === "setup"}
      {#if blocked}<p class="note">This scenario executes code and needs a sandbox, which this runtime does not have. Use the local app.</p>{/if}
      <p class="lead">Start from a baseline, then change the model of any step. Steps share a model when they use the same
        role. Parameters and the control policy change the workflow, and the diagram follows.</p>
      <label class="name">Setup name <input type="text" bind:value={config.name} /></label>
      <ScenarioSetup {manifest} bind:config showPolicy />

      <h2>Run it</h2>
      {#if onlyTask}
        <p class="note" role="status">Only task <code>{onlyTask}</code> will run. <button class="link" onclick={() => (onlyTask = "")}>Run a sample of tasks instead</button></p>
      {/if}
      <section class="card settings">
        {#if !onlyTask}<label>Tasks (empty = all {manifest.tasks})<input type="number" min="1" bind:value={limit} /></label>{/if}
        <label>Repeats per task<input type="number" min="1" max="10" bind:value={repeats} /></label>
        {#if manifest.supports_decisions && !onlyTask}
          <label>Task split<select bind:value={split}><option value="all">all</option><option value="dev">dev (tuning)</option><option value="test">test (reporting)</option></select></label>
        {/if}
        <label>Spend limit (USD)<input type="number" min="0" step="0.5" bind:value={maxCostUsd} /></label>
      </section>
      {#if errors.length}<ul class="errors">{#each errors as e (e)}<li>{e}</li>{/each}</ul>{/if}
      <div class="actions">
        <button onclick={runEstimate} disabled={busy || errors.length > 0 || blocked}>Estimate cost</button>
        <button class="primary" onclick={start} disabled={busy || errors.length > 0 || blocked}>Run this setup</button>
        <button onclick={addToExperiment} disabled={errors.length > 0}>Add to experiment builder</button>
        {#if estimate}<span>{estimate.trials} trials · ~{estimate.tokens.toLocaleString("en-US")} tokens · ~{usd(estimate.cost_usd)}</span>{/if}
      </div>
      {#if message}<p class="note" role="status">{message}</p>{/if}
    {:else}
      <p class="lead">Every comparable run of this scenario, pooled per setup (models per step, parameters, control policy).
        <a href="#/leaderboard">All scenarios →</a></p>
      {#if board === null}
        <div class="skeleton" aria-busy="true"></div>
      {:else if board.length}
        <div class="card table-wrap">
          <table>
            <thead><tr><th class="n">#</th><th>Setup</th><th>Models per role</th><th class="n">Pass rate [95% CI]</th><th class="n">Tasks</th><th class="n">$/trial</th><th class="n">p50 s</th><th><span class="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {#each board as e (e.fingerprint)}
                <tr>
                  <td class="n">{e.rank}</td>
                  <td><strong>{e.config}</strong><div class="muted small">{e.setup.decisions ? `${(e.setup.decisions as { policy?: string }).policy} policy` : "agent decides"}</div></td>
                  <td class="small">{#each models(e) as m (m)}<div>{m}</div>{/each}</td>
                  <td class="n">{pct(e.pass_rate)} <span class="muted">[{pct(e.ci_low)}–{pct(e.ci_high)}]</span></td>
                  <td class="n">{e.tasks}</td><td class="n">{usd(e.mean_cost_usd)}</td><td class="n">{num(e.latency_p50_s, 1)}</td>
                  <td><button onclick={() => useSetup(e)}>Use this setup</button></td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else}
        <div class="empty card">
          <p><strong>No results yet.</strong> Run a setup and it appears here, ranked against every other setup of this scenario.</p>
          <button class="primary" onclick={() => show("setup")}>Choose models and run →</button>
        </div>
      {/if}
    {/if}
  </div>
{/if}

<style>
  .crumbs { font-size: 13px; color: var(--text-muted); margin: 0 0 6px; }
  .small { font-size: 12px; }
  [role="tabpanel"]:focus { outline: none; }
  .overview { display: grid; grid-template-columns: minmax(280px, 1fr) minmax(300px, 1fr); gap: 20px; align-items: start; }
  @media (max-width: 900px) { .overview { grid-template-columns: 1fr; } }
  .facts { display: grid; gap: 14px; }
  .facts h3 { margin: 0 0 4px; font-size: 14px; }
  .facts p, .facts ul { margin: 0; }
  .facts ul { padding-left: 18px; }
  dl { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; }
  dt { font-family: ui-monospace, monospace; font-size: 12.5px; color: var(--text-secondary); padding-top: 2px; }
  dd { margin: 0; }
  .preview h3 { margin: 0 0 8px; font-size: 14px; }
  .name { display: flex; gap: 8px; align-items: center; margin: 0 0 12px; font-size: 14px; }
  .settings { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
  .settings label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 12px 0; }
  .errors { color: var(--critical); font-size: 13px; }
  .link { background: none; border: none; color: var(--accent); padding: 0; text-decoration: underline; cursor: pointer; }
  .empty { display: grid; gap: 10px; justify-items: start; }
  .empty p { margin: 0; }
  .skeleton { height: 120px; border-radius: var(--radius); background: var(--surface-2); }
</style>
