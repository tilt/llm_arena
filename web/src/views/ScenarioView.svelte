<script lang="ts">
  import ScenarioSetup from "../components/ScenarioSetup.svelte";
  import { app } from "../lib/app.svelte";
  import { EVALUATION_PAGES, emptyConfig, toExperiment, validate, type BuilderState, type ConfigDraft } from "../lib/builder";
  import type { Estimate, LeaderboardEntry } from "../lib/contracts";
  import { addToDraft } from "../lib/draft.svelte";
  import { num, pct, usd } from "../lib/format";
  import { go } from "../lib/router.svelte";
  import { configFromSetup } from "../lib/setups";

  let { id }: { id: string } = $props();
  const manifest = $derived(app.scenarios.find((s) => s.id === id));

  let config = $state<ConfigDraft>({ ...emptyConfig(0), name: "my-setup" });
  let limit = $state<number | null>(3);
  let repeats = $state(1);
  let split = $state<"all" | "dev" | "test">("all");
  let maxCostUsd = $state<number | null>(1);
  let estimate = $state<Estimate | null>(null);
  let message = $state("");
  let busy = $state(false);
  let board = $state<LeaderboardEntry[]>([]);

  $effect(() => {
    if (!app.backend) return;
    app.backend.leaderboard().then((boards) => {
      board = boards.filter((b) => b.scenario === id && b.scenario_version !== "legacy").flatMap((b) => b.entries).slice(0, 8);
    }, () => (board = []));
  });

  const plan = $derived<BuilderState>({
    name: `${id}-${config.name}`.replace(/[^\w.-]+/g, "-"), scenarios: [id], configs: [config], repeats, limit, judge: "",
    arena: false, maxCostUsd, split,
  });
  const errors = $derived(manifest ? validate(plan, app.scenarios, app.runtime?.sandbox ?? false,
    Object.fromEntries(Object.entries(app.runtime?.decision_services ?? {}).map(([k, v]) => [k, v?.status ?? ""]))) : []);
  const blocked = $derived((manifest?.requires ?? []).includes("sandbox") && !app.runtime?.sandbox);

  async function runEstimate() {
    if (!app.backend) return;
    busy = true; message = "";
    try { estimate = await app.backend.estimate(toExperiment(plan, app.scenarios)); }
    catch (e) { message = e instanceof Error ? e.message : String(e); }
    finally { busy = false; }
  }
  async function start() {
    if (!app.backend) return;
    busy = true; message = "";
    try {
      const runId = await app.backend.startRun({ experiment: toExperiment(plan, app.scenarios), live: false });
      go(`/runs/${encodeURIComponent(runId)}`);
    } catch (e) { message = e instanceof Error ? e.message : String(e); busy = false; }
  }
  function addToExperiment() {
    addToDraft(id, $state.snapshot(config) as ConfigDraft);
    go("/build");
  }
  function useSetup(entry: LeaderboardEntry) {
    const { config: loaded, exact } = configFromSetup(id, entry.config, entry.setup, app.models?.aliases ?? {});
    config = loaded;
    message = exact ? `Loaded the setup of "${entry.config}".`
      : `Loaded "${entry.config}". Some call settings (e.g. thinking off) have no model alias here; check the models.`;
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
  <p class="lead">{manifest.description}</p>
  <p class="muted small">{manifest.tasks} tasks · pass criteria: {manifest.pass_criteria.join(", ")} · version {manifest.version}
    {#each (manifest.wiki ?? []).filter((l) => !EVALUATION_PAGES.has(l.title)) as link (link.url)} · <a href={link.url} target="_blank" rel="noopener">{link.title}</a>{/each}</p>
  {#if blocked}<p class="note">This scenario executes code and needs a sandbox, which this runtime does not have. Use the local app.</p>{/if}

  <h2>Workflow and models</h2>
  <p class="lead">Choose a model for each step. Steps share a model when they use the same role; unset roles use their
    fallback or the default model. Parameters and the control policy change the workflow, and the diagram follows.</p>
  <label class="name">Setup name <input type="text" bind:value={config.name} /></label>
  <ScenarioSetup {manifest} bind:config showPolicy />

  <h2>Run it</h2>
  <section class="card settings">
    <label>Tasks (empty = all {manifest.tasks})<input type="number" min="1" bind:value={limit} /></label>
    <label>Repeats per task<input type="number" min="1" max="10" bind:value={repeats} /></label>
    {#if manifest.supports_decisions}
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
  {#if message}<p class="note">{message}</p>{/if}

  <h2>Leaderboard <a class="small" href="#/leaderboard">all scenarios →</a></h2>
  {#if board.length}
    <div class="card table-wrap">
      <table>
        <thead><tr><th class="n">#</th><th>Setup</th><th>Models per role</th><th class="n">Pass rate [95% CI]</th><th class="n">Tasks</th><th class="n">$/trial</th><th></th></tr></thead>
        <tbody>
          {#each board as e (e.fingerprint)}
            <tr>
              <td class="n">{e.rank}</td>
              <td><strong>{e.config}</strong><div class="muted small">{e.setup.decisions ? `${(e.setup.decisions as { policy?: string }).policy} policy` : "agent decides"}</div></td>
              <td class="small">{#each models(e) as m (m)}<div>{m}</div>{/each}</td>
              <td class="n">{pct(e.pass_rate)} <span class="muted">[{pct(e.ci_low)}–{pct(e.ci_high)}]</span></td>
              <td class="n">{e.tasks}</td><td class="n">{usd(e.mean_cost_usd)}</td>
              <td><button onclick={() => useSetup(e)}>Use this setup</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="muted small">Latency p50 of the leader: {num(board[0]?.latency_p50_s, 1)} s. "Use this setup" loads its models, parameters and control policy above.</p>
  {:else}
    <p class="muted">No versioned results yet. Run a setup and it appears here.</p>
  {/if}
{/if}

<style>
  .crumbs { font-size: 13px; color: var(--text-muted); margin: 0 0 6px; }
  .small { font-size: 12px; }
  .name { display: flex; gap: 8px; align-items: center; margin: 0 0 12px; font-size: 14px; }
  .settings { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
  .settings label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 12px 0; }
  .errors { color: var(--critical); font-size: 13px; }
</style>
