<script lang="ts">
  import ModelSelect from "../components/ModelSelect.svelte";
  import ScenarioSetup from "../components/ScenarioSetup.svelte";
  import StudyForm from "../components/StudyForm.svelte";
  import { app } from "../lib/app.svelte";
  import {
    CONTROLS, DEFAULT_ROLE, EVALUATION_PAGES, POLICIES, controllableScenarios, defaultRoleNeeds, eligibleModels, emptyConfig,
    roleSlots, SERVICE_LABELS, servicesUsed, toExperiment, toYaml, validate, validateStudy, type BuilderState, type ConfigDraft,
    type Service,
  } from "../lib/builder";
  import type { Estimate } from "../lib/contracts";
  import { usd } from "../lib/format";
  import { activeBaseline } from "../lib/baselines";
  import { draft } from "../lib/draft.svelte";
  import { go } from "../lib/router.svelte";
  import { refreshRuns } from "../lib/runs.svelte";

  // The draft lives in a shared store so scenario pages can add configured setups to it.

  let estimate = $state<Estimate | null>(null);
  let busy = $state(false);
  let message = $state("");
  let live = $state(false);

  const catalog = $derived(app.models?.models ?? []);
  const sandbox = $derived(app.runtime?.sandbox ?? false);
  const slots = $derived(roleSlots(app.scenarios, draft.scenarios));
  const selected = $derived(app.scenarios.filter((s) => draft.scenarios.includes(s.id)));
  const openEnded = $derived(selected.some((s) => s.open_ended));
  const services = $derived(app.runtime?.decision_services ?? {});
  const serviceStatus = $derived(Object.fromEntries(Object.entries(services).map(([k, v]) => [k, v?.status ?? ""])) as Record<Service, string>);
  const available = (service: string) => services[service]?.status === "available";
  const errors = $derived(draft.study ? validateStudy(draft, draft.study) : validate(draft, app.scenarios, sandbox, serviceStatus));
  function setMode(study: boolean) {
    draft.study = study ? { baseline: activeBaseline(), candidates: [""], roles: [], decisionControl: "gate" } : null;
    estimate = null;
  }
  const controllable = $derived(controllableScenarios(draft, app.scenarios));
  const hasSplits = $derived(controllable.length > 0);
  const experiment = () => toExperiment(draft, app.scenarios, app.baselines);

  const SERVICES_SHOWN: Service[] = ["jev", "ollaya"];

  function setPolicy(config: ConfigDraft, value: string) {
    const base = config.decisions ?? { control: "policy", threshold: 0.8, ollaya_model: services.ollaya?.models?.[0] ?? "winnow:e4b" };
    config.decisions = value ? { ...base, policy: value as never } : null;
  }

  function toggleScenario(id: string) {
    draft.scenarios = draft.scenarios.includes(id) ? draft.scenarios.filter((s) => s !== id) : [...draft.scenarios, id];
    estimate = null;
  }
  function addConfig() {
    const base = draft.configs.at(-1);
    draft.configs = [...draft.configs, { ...emptyConfig(draft.configs.length), roles: { ...emptyConfig(0).roles, ...(base?.roles ?? {}) }, baseline: base?.baseline ?? activeBaseline() }];
  }

  async function runEstimate() {
    if (!app.backend) return;
    busy = true;
    message = "";
    try {
      estimate = await app.backend.estimate(experiment());
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
      const runId = await app.backend.startRun({ experiment: experiment(), live });
      void refreshRuns(); // the Runs badge and list show it at once
      go(`/runs/${encodeURIComponent(runId)}`);
    } catch (error) {
      message = error instanceof Error ? error.message : String(error);
      busy = false;
    }
  }
  function downloadYaml() {
    const blob = new Blob([toYaml(experiment())], { type: "text/yaml" });
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

<section class="card intro">
  <label for="exp-name">Experiment name</label>
  <input id="exp-name" type="text" bind:value={draft.name} />
  <div class="mode" role="radiogroup" aria-label="What do you want to find out?">
    <label class:on={!draft.study}><input type="radio" name="mode" checked={!draft.study} onchange={() => setMode(false)} />
      <span><strong>Compare configurations</strong><br /><span class="muted">set up one or more complete setups and rank them</span></span></label>
    <label class:on={!!draft.study}><input type="radio" name="mode" checked={!!draft.study} onchange={() => setMode(true)} />
      <span><strong>Replacement study</strong><br /><span class="muted">start from a baseline and measure what swapping one step's model changes</span></span></label>
  </div>
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

{#if draft.study}
<h2>2 · Study</h2>
<StudyForm bind:study={draft.study} manifests={app.scenarios.filter((s) => draft.scenarios.includes(s.id))} />
{:else}
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
        <label class="role-name" for={`baseline-${index}`}>Start from <span class="muted">(a baseline gives each step a model by the kind of work it does; <a href="#/settings">edit baselines</a>)</span></label>
        <select id={`baseline-${index}`} bind:value={config.baseline}>
          <option value="">no baseline: one default model</option>
          {#each Object.entries(app.baselines) as [name, p] (name)}<option value={name}>{p.label}</option>{/each}
        </select>
      </div>
      {#if !config.baseline}
      <div class="role">
        <span class="role-name">Default model <span class="muted">(every step not set per scenario below{defaultRoleNeeds(slots, config).length ? `; needs ${defaultRoleNeeds(slots, config).join(", ")}` : ""})</span></span>
        <ModelSelect bind:value={config.roles[DEFAULT_ROLE]} options={eligibleModels(catalog, defaultRoleNeeds(slots, config))} empty="— choose —" label="Default model" />
      </div>
      {/if}
    </div>
    {#if controllable.length}
      <div class="params control">
        <span class="muted">Control policy ({controllable.join(", ")}):</span>
        <label class="param">policy
          <select value={config.decisions?.policy ?? ""} onchange={(e) => setPolicy(config, e.currentTarget.value)}>
            <option value="">none (the agent decides)</option>
            {#each POLICIES as p (p.value)}<option value={p.value} disabled={(p.value === "jev" || p.value === "ollaya") && !available(p.value)}>{p.label}</option>{/each}
          </select>
        </label>
        {#if config.decisions}
          <label class="param">mode
            <select bind:value={config.decisions.control}>
              {#each CONTROLS as c (c.value)}<option value={c.value}>{c.label}</option>{/each}
            </select>
          </label>
          {#if config.decisions.policy === "cascade"}
            <label class="param">primary
              <select bind:value={config.decisions.primary}><option value="llm">LLM (decider)</option><option value="jev" disabled={!available("jev")}>Jev</option><option value="ollaya" disabled={!available("ollaya")}>Ollaya</option></select>
            </label>
            <label class="param">fallback
              <select bind:value={config.decisions.fallback}><option value="llm">LLM (escalation)</option><option value="jev" disabled={!available("jev")}>Jev</option><option value="ollaya" disabled={!available("ollaya")}>Ollaya</option><option value={null}>none</option></select>
            </label>
            <label class="param">escalate below<input type="number" min="0" max="1" step="0.05" bind:value={config.decisions.threshold} /></label>
          {/if}
          {#if servicesUsed(config.decisions).includes("ollaya")}
            <label class="param">Ollaya model
              <select bind:value={config.decisions.ollaya_model}>
                {#each services.ollaya?.models ?? ["winnow:e4b"] as m (m)}<option value={m}>{m}</option>{/each}
              </select>
            </label>
          {/if}
          {#each SERVICES_SHOWN.filter((s) => !available(s)) as s (s)}
            <span class="muted jev">{SERVICE_LABELS[s]}: {services[s]?.status ?? "unknown"}</span>
          {/each}
        {/if}
      </div>
    {/if}
    {#each selected as s (s.id)}
      <details class="scenario-setup" open={selected.length === 1}>
        <summary><strong>{s.title}</strong> <span class="muted">— steps, models and parameters</span></summary>
        <ScenarioSetup manifest={s} bind:config={draft.configs[index]!} showDefault={false} showBaseline={false} />
      </details>
    {/each}
  </section>
{/each}
<button onclick={addConfig}>+ Add configuration</button>
{/if}

<h2>3 · Run settings</h2>
<section class="card settings">
  <label>Repeats per task (pass^k)<input type="number" min="1" max="10" bind:value={draft.repeats} /></label>
  <label>Tasks per scenario (empty = all)<input type="number" min="1" bind:value={draft.limit} /></label>
  {#if hasSplits}
    <label>Task split
      <select bind:value={draft.split}>
        <option value="all">all tasks</option><option value="dev">dev (tune thresholds)</option><option value="test">test (report)</option>
      </select>
    </label>
  {/if}
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
  .intro { display: grid; gap: 8px; }
  .mode { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 8px; margin-top: 8px; }
  .mode label { display: flex; gap: 10px; align-items: start; border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 12px; cursor: pointer; font-size: 14px; }
  .mode label.on { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
  .mode .muted { font-size: 13px; }
  .scenario-setup { margin-top: 12px; border-top: 1px solid var(--border); padding-top: 8px; }
  .scenario-setup summary { cursor: pointer; margin-bottom: 8px; }
  .params { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-top: 10px; font-size: 13px; }
  .param { display: flex; gap: 6px; align-items: center; }
  .param input[type="number"] { width: 70px; }
  .control { padding-top: 8px; border-top: 1px solid var(--border); }
  .jev { font-size: 12px; }
  .settings { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
  .settings label { display: flex; flex-direction: column; gap: 4px; }
  .settings label.inline { flex-direction: row; align-items: center; }
  .errors { color: var(--critical); font-size: 13px; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 16px 0 40px; }
  .estimate { font-size: 14px; }
</style>
