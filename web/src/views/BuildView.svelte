<script lang="ts">
  import ModelSelect from "../components/ModelSelect.svelte";
  import { app } from "../lib/app.svelte";
  import {
    DEFAULT_ROLE, EVALUATION_PAGES, defaultRoleNeeds, eligibleModels, emptyConfig, roleSlots, toExperiment, toYaml, validate,
    type BuilderState,
  } from "../lib/builder";
  import type { Estimate, ParamManifest } from "../lib/contracts";
  import { usd } from "../lib/format";
  import { go } from "../lib/router.svelte";

  let draft = $state<BuilderState>({
    name: "my-experiment", scenarios: [], configs: [emptyConfig(0)], repeats: 1, limit: 3, judge: "", arena: false, maxCostUsd: 1,
  });
  let estimate = $state<Estimate | null>(null);
  let busy = $state(false);
  let message = $state("");
  let live = $state(false);

  const catalog = $derived(app.models?.models ?? []);
  const sandbox = $derived(app.runtime?.sandbox ?? false);
  const slots = $derived(roleSlots(app.scenarios, draft.scenarios));
  const selected = $derived(app.scenarios.filter((s) => draft.scenarios.includes(s.id)));
  const openEnded = $derived(selected.some((s) => s.open_ended));
  const errors = $derived(validate(draft, app.scenarios, sandbox));

  function toggleScenario(id: string) {
    draft.scenarios = draft.scenarios.includes(id) ? draft.scenarios.filter((s) => s !== id) : [...draft.scenarios, id];
    estimate = null;
  }
  function addConfig() {
    const base = draft.configs.at(-1);
    draft.configs = [...draft.configs, { ...emptyConfig(draft.configs.length), roles: { ...emptyConfig(0).roles, ...(base?.roles ?? {}) } }];
  }
  function setParam(configIndex: number, scenario: string, param: ParamManifest, raw: string | boolean) {
    const config = draft.configs[configIndex]!;
    const value = param.type === "boolean" ? Boolean(raw) : param.type === "integer" ? parseInt(String(raw), 10)
      : param.type === "number" ? parseFloat(String(raw)) : raw;
    const current = { ...(config.scenarioParams[scenario] ?? {}) };
    if (value === param.default || (typeof value === "number" && Number.isNaN(value))) delete current[param.name];
    else current[param.name] = value;
    config.scenarioParams = { ...config.scenarioParams, [scenario]: current };
  }
  const paramValue = (configIndex: number, scenario: string, param: ParamManifest) =>
    draft.configs[configIndex]?.scenarioParams[scenario]?.[param.name] ?? param.default;

  async function runEstimate() {
    if (!app.backend) return;
    busy = true;
    message = "";
    try {
      estimate = await app.backend.estimate(toExperiment(draft));
    } catch (error) {
      message = error instanceof Error ? error.message : String(error);
    } finally {
      busy = false;
    }
  }
  async function start() {
    if (!app.backend) return;
    busy = true;
    try {
      const runId = await app.backend.startRun({ experiment: toExperiment(draft), live });
      go(`/runs/${encodeURIComponent(runId)}`);
    } catch (error) {
      message = error instanceof Error ? error.message : String(error);
      busy = false;
    }
  }
  function downloadYaml() {
    const blob = new Blob([toYaml(toExperiment(draft))], { type: "text/yaml" });
    const link = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `${draft.name || "experiment"}.yaml` });
    link.click();
    URL.revokeObjectURL(link.href);
  }
</script>

<h1>Build an experiment</h1>
<p class="lead">
  Pick scenarios, then add one or more model configurations to compare. Each configuration binds a model to every
  pipeline role, for example a local model drafting and a remote model critiquing.
</p>

<section class="card">
  <label for="exp-name">Experiment name</label>
  <input id="exp-name" type="text" bind:value={draft.name} />
</section>

<h2>1 · Scenarios</h2>
{#each [["pattern", "Agentic patterns"], ["benchmark", "Benchmarks"]] as [kind, heading] (kind)}
  <h3>{heading}</h3>
  <div class="scenarios">
    {#each app.scenarios.filter((s) => s.kind === kind) as s (s.id)}
      {@const blocked = (s.requires ?? []).includes("sandbox") && !sandbox}
      <label class="scenario card" class:chosen={draft.scenarios.includes(s.id)} class:blocked title={blocked ? "Needs a code sandbox, which this runtime does not have" : ""}>
        <input type="checkbox" checked={draft.scenarios.includes(s.id)} disabled={blocked} onchange={() => toggleScenario(s.id)} />
        <span class="body">
          <strong>{s.title}</strong>
          <span class="desc">{s.description}</span>
          <span class="meta">{s.tasks} tasks · {s.roles.map((r) => r.name + ((r.needs ?? []).length ? ` [${r.needs?.join(",")}]` : "")).join(", ")}
            {#each (s.wiki ?? []).filter((link) => !EVALUATION_PAGES.has(link.title)) as link (link.url)} · <a href={link.url} target="_blank" rel="noopener" onclick={(e) => e.stopPropagation()}>{link.title}</a>{/each}</span>
        </span>
      </label>
    {/each}
  </div>
{/each}

<h2>2 · Model configurations</h2>
{#if !draft.scenarios.length}<p class="muted">Select a scenario first.</p>{/if}
{#each draft.configs as config, index (index)}
  <section class="card config">
    <div class="config-head">
      <input type="text" bind:value={config.name} aria-label="Configuration name" />
      {#if draft.configs.length > 1}<button onclick={() => (draft.configs = draft.configs.filter((_, i) => i !== index))}>Remove</button>{/if}
    </div>
    <div class="roles">
      <div class="role">
        <span class="role-name">Default model <span class="muted">(every role not set below{defaultRoleNeeds(slots, config).length ? `; needs ${defaultRoleNeeds(slots, config).join(", ")}` : ""})</span></span>
        <ModelSelect bind:value={config.roles[DEFAULT_ROLE]} options={eligibleModels(catalog, defaultRoleNeeds(slots, config))} empty="— choose —" label="Default model" />
      </div>
      {#each slots as slot (slot.name)}
        <div class="role">
          <span class="role-name">{slot.name} <span class="muted">{slot.description}{slot.optional ? " · optional" : ""}{slot.needs.length ? ` · needs ${slot.needs.join(", ")}` : ""}</span></span>
          <ModelSelect bind:value={config.roles[slot.name]} options={eligibleModels(catalog, slot.needs)} empty={slot.optional ? "same as its fallback role" : "use default model"} label={`Model for ${slot.name}`} />
        </div>
      {/each}
    </div>
    {#each selected.filter((s) => s.params.some((p) => p.choices || p.type === "boolean" || p.name.includes("rounds"))) as s (s.id)}
      <div class="params">
        <span class="muted">{s.title}:</span>
        {#each s.params.filter((p) => p.choices || p.type === "boolean" || p.name.includes("rounds")) as p (p.name)}
          <label class="param">{p.name}
            {#if p.choices}
              <select value={String(paramValue(index, s.id, p))} onchange={(e) => setParam(index, s.id, p, e.currentTarget.value)}>
                {#each p.choices as choice (choice)}<option value={String(choice)}>{choice}</option>{/each}
              </select>
            {:else if p.type === "boolean"}
              <input type="checkbox" checked={Boolean(paramValue(index, s.id, p))} onchange={(e) => setParam(index, s.id, p, e.currentTarget.checked)} />
            {:else}
              <input type="number" min="0" value={String(paramValue(index, s.id, p))} onchange={(e) => setParam(index, s.id, p, e.currentTarget.value)} />
            {/if}
          </label>
        {/each}
      </div>
    {/each}
  </section>
{/each}
<button onclick={addConfig}>+ Add configuration</button>

<h2>3 · Run settings</h2>
<section class="card settings">
  <label>Repeats per task (pass^k)<input type="number" min="1" max="10" bind:value={draft.repeats} /></label>
  <label>Tasks per scenario (empty = all)<input type="number" min="1" bind:value={draft.limit} /></label>
  <label>Spend limit (USD)<input type="number" min="0" step="0.5" bind:value={draft.maxCostUsd} /></label>
  <label>Judge model (rubric scores{openEnded ? ", arena" : ""})
    <ModelSelect bind:value={draft.judge} options={catalog} empty="no judge" label="Judge model" /></label>
  {#if openEnded}<label class="inline"><input type="checkbox" bind:checked={draft.arena} /> Pairwise arena battles (needs a judge)</label>{/if}
  {#if app.runtime?.live_search}<label class="inline"><input type="checkbox" bind:checked={live} /> Allow live web/arXiv search</label>{/if}
</section>

{#if errors.length}
  <ul class="errors">{#each errors as e (e)}<li>{e}</li>{/each}</ul>
{/if}
<div class="actions">
  <button onclick={runEstimate} disabled={busy || errors.length > 0}>Estimate cost</button>
  <button class="primary" onclick={start} disabled={busy || errors.length > 0}>Start run</button>
  <button onclick={downloadYaml} disabled={!draft.scenarios.length}>Download YAML</button>
  {#if estimate}
    <span class="estimate">{estimate.trials} trials · ~{estimate.tokens.toLocaleString("en-US")} tokens · ~{usd(estimate.cost_usd)}
      {#if estimate.unknown_prices?.length}<span class="muted"> (no price for {estimate.unknown_prices.join(", ")})</span>{/if}</span>
  {/if}
</div>
{#if message}<p class="note">{message}</p>{/if}

<style>
  .scenarios { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 10px; }
  .scenario { display: flex; gap: 10px; cursor: pointer; }
  .scenario.chosen { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
  .scenario.blocked { opacity: 0.55; cursor: not-allowed; }
  .body { display: flex; flex-direction: column; gap: 4px; font-size: 14px; }
  .desc { color: var(--text-secondary); font-size: 13px; }
  .meta { color: var(--text-muted); font-size: 12px; }
  .config { margin-bottom: 12px; }
  .config-head { display: flex; gap: 8px; margin-bottom: 8px; }
  .config-head input { font-weight: 600; }
  .roles { display: grid; gap: 8px; }
  .role { display: grid; grid-template-columns: minmax(200px, 1fr) minmax(220px, 1.2fr); gap: 10px; align-items: center; }
  @media (max-width: 720px) { .role { grid-template-columns: 1fr; } }
  .role-name { font-size: 14px; }
  .role-name .muted { font-size: 12px; }
  .params { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-top: 10px; font-size: 13px; }
  .param { display: flex; gap: 6px; align-items: center; }
  .param input[type="number"] { width: 70px; }
  .settings { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
  .settings label { display: flex; flex-direction: column; gap: 4px; }
  .settings label.inline { flex-direction: row; align-items: center; }
  .errors { color: var(--critical); font-size: 13px; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 16px 0 40px; }
  .estimate { font-size: 14px; }
</style>
