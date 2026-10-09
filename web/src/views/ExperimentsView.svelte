<script lang="ts">
  import { untrack } from "svelte";
  import ConfigCard from "../components/ConfigCard.svelte";
  import ModelRefInput from "../components/ModelRefInput.svelte";
  import ModelSelect from "../components/ModelSelect.svelte";
  import SwapPanel from "../components/SwapPanel.svelte";
  import VariantCard from "../components/VariantCard.svelte";
  import { app } from "../lib/app.svelte";
  import {
    EVALUATION_PAGES, bundleModels, bundleSource, configForModel, configForPreset, eligibleModels, expandConfigs, kindExceptions, kindsUsed,
    lacking, llmRoles, configId, plannedTrials, roleSlots, suggestName, swapProblem, toExperiment, toYaml, validate, type ConfigDraft, type Service,
  } from "../lib/builder";
  import type { Estimate } from "../lib/contracts";
  import { usd } from "../lib/format";
  import { KINDS, describeRef, splitRef } from "../lib/presets";
  import { draft } from "../lib/draft.svelte";
  import { go, replace } from "../lib/router.svelte";
  import { refreshRuns } from "../lib/runs.svelte";
  import { SUITES, applySuite, clearSuite, suiteChanges, suiteScenarios } from "../lib/scenario-groups";

  // One page, three questions: what to run (a suite fills it in), which models (setups: one evaluates, more compare),
  // how much (trials and run settings). The draft lives in a shared store so scenario pages can add setups to it.
  // In code a setup in this table is a "bundle" (ConfigDraft): a model per step kind, run under every variant.
  // A suite link (#/experiments/<suite>) selects that suite once, then the address goes back to #/experiments.
  let { template = "" }: { template?: string } = $props();

  let estimate = $state<Estimate | null>(null);
  let busy = $state(false);
  let message = $state("");
  let live = $state(false);
  let pickSuite = $state(false);
  let pickScenarios = $state(false);
  let editVariant = $state<number | null>(null);
  let editCell = $state<{ index: number; kind: string } | null>(null);
  let details = $state<number | null>(null);
  let addModel = $state("");
  // The swap panel, open with the steps it preselects (a suite's), or closed (null).
  let swapping = $state<string[] | null>(null);

  const catalog = $derived(app.models?.models ?? []);
  const sandbox = $derived(app.runtime?.sandbox ?? false);
  const slots = $derived(roleSlots(app.scenarios, draft.scenarios));
  const selected = $derived(app.scenarios.filter((s) => draft.scenarios.includes(s.id)));
  const openEnded = $derived(selected.some((s) => s.open_ended));
  const services = $derived(app.runtime?.decision_services ?? {});
  const serviceStatus = $derived(Object.fromEntries(Object.entries(services).map(([k, v]) => [k, v?.status ?? ""])) as Record<Service, string>);
  const errors = $derived(validate(draft, app.scenarios, sandbox, serviceStatus, app.presets, catalog));
  const controllable = $derived(selected.some((s) => s.supports_decisions));
  // Scenarios a policy-carrying run leaves out (the trial count already does; the formula above it cannot say so).
  const skipped = $derived(expandConfigs(draft).some(({ bundle }) => bundle.decisions)
    ? selected.filter((s) => !s.supports_decisions).map((s) => s.title) : []);
  const planned = $derived(plannedTrials(draft, app.scenarios));
  const baseline = $derived(draft.configs.find((c) => c.baseline));
  const suite = $derived(SUITES.find((s) => s.id === draft.suite));
  const changes = $derived(suite ? suiteChanges(draft, suite, app.scenarios) : []);
  const variants = $derived(draft.variants ?? []);
  const decides = $derived(expandConfigs(draft).some(({ bundle }) => llmRoles(bundle.decisions).length > 0));
  // Columns of the setup table: the step kinds the selected scenarios use (all but decision before any are chosen).
  const kinds = $derived.by(() => {
    const used = kindsUsed(draft, app.scenarios);
    return used.length ? used : KINDS.filter((k) => k.kind !== "decision").map((k) => ({ kind: k.kind, roles: [] as string[], needs: [] as string[] }));
  });
  // A setup on one model runs every step on it, so the model needs what every step needs.
  const allNeeds = $derived([...new Set(kinds.flatMap((k) => k.needs))].sort());
  // Steps a swap can change: those of the table's columns (decision steps only when a policy calls an LLM).
  const swapRoles = $derived([...new Set(kinds.flatMap((k) => k.roles))].sort());
  const titles = (ids: string[] = []) => ids.map((id) => app.scenarios.find((m) => m.id === id)?.title ?? id).join(", ");
  const kindLabel = (kind: string) => KINDS.find((k) => k.kind === kind)?.label ?? kind;
  const showSuites = $derived(pickSuite || (!suite && !draft.scenarios.length));
  const experiment = () => toExperiment(draft, app.scenarios, app.presets);
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const differ = (list: { role: string; scenario: string; model: string }[]) =>
    list.map((e) => `${e.role} in ${e.scenario}: ${describeRef(e.model)}`).join("\n");

  // Setups are named after their models until the user types a name; equal suggestions get -2, -3.
  $effect(() => {
    const taken = new Set(draft.configs.filter((c) => c.named).map((c) => c.name));
    for (const config of draft.configs.filter((c) => !c.named)) {
      const base = suggestName(config, app.presets, draft.scenarios);
      let name = base;
      for (let i = 2; taken.has(name); i++) name = `${base}-${i}`;
      taken.add(name);
      if (config.name !== name) config.name = name;
    }
  });

  // Every setup gets a stable id, so swaps keep pointing at the setup they were made from when names change.
  $effect(() => {
    for (const config of draft.configs) if (!config.id) config.id = configId();
  });

  // An estimate belongs to the draft it was made for; any change makes it stale.
  $effect(() => {
    JSON.stringify(draft);
    untrack(() => (estimate = null));
  });

  $effect(() => {
    if (!template || !app.scenarios.length) return;
    untrack(() => {
      if (draft.suite !== template && SUITES.some((s) => s.id === template)) useSuite(template);
      replace("/experiments");
    });
  });

  function useSuite(id: string) {
    const chosen = SUITES.find((s) => s.id === id);
    if (!chosen) return;
    applySuite(draft, chosen, app.scenarios, app.presets);
    pickSuite = false;
    pickScenarios = false;
    editVariant = null;
    swapping = chosen.swaps ? [...chosen.swaps.roles] : null;
  }
  function removeSuite() {
    clearSuite(draft);
    pickSuite = false;
    pickScenarios = false;
    editVariant = null;
    swapping = null;
  }
  function toggleScenario(id: string) {
    draft.scenarios = draft.scenarios.includes(id) ? draft.scenarios.filter((s) => s !== id) : [...draft.scenarios, id];
  }
  function addVariant() {
    const taken = new Set(variants.map((v) => v.name));
    let name = variants.length ? `variant-${variants.length + 1}` : "plain";
    for (let i = 2; taken.has(name); i++) name = `variant-${i}`;
    draft.variants = [...variants, { name, params: {}, decisions: null }];
    editVariant = draft.variants.length - 1;
  }
  function removeVariant(index: number) {
    draft.variants = variants.filter((_, i) => i !== index);
    editVariant = null;
  }
  function setBaseline(index: number, on: boolean) {
    draft.configs.forEach((c, i) => (c.baseline = on && i === index));
  }
  function addSwaps(base: number, setups: ConfigDraft[]) {
    setBaseline(base, true);
    const taken = new Set(draft.configs.map((c) => c.name));
    for (const setup of setups) {
      let name = setup.name;
      for (let i = 2; taken.has(name); i++) name = `${setup.name}-${i}`;
      taken.add(name);
      setup.name = name;
    }
    draft.configs = [...draft.configs, ...setups];
    swapping = null;
  }
  function addBundle(config: ConfigDraft) {
    draft.configs = [...draft.configs, config];
  }
  function removeBundle(index: number) {
    draft.configs = draft.configs.filter((_, i) => i !== index);
    editCell = null;
    details = null;
  }
  // A cell's own model, over the setup's preset (or one model) for that kind; "" goes back to it.
  const baseModel = (config: ConfigDraft, kind: string) => bundleModels({ ...config, kinds: {} }, app.presets)[kind] ?? "";
  function setKind(config: ConfigDraft, kind: string, ref: string) {
    const next = { ...(config.kinds ?? {}), [kind]: ref };
    if (!ref) delete next[kind];
    config.kinds = next;
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

<h1>Experiments</h1>
<p class="lead">What to run, which models, how much. Every experiment is also a YAML file the CLI runs.</p>
<div class="line name-line">
  <label class="label" for="exp-name">Name</label>
  <span class="value">
    <input id="exp-name" class="exp-name" type="text" bind:value={draft.name} />
    <span class="muted small">names the run and the YAML file{suite ? "; a suite sets it" : ""}</span>
  </span>
</div>

<section class="step" aria-labelledby="what-title">
  <h2 id="what-title"><span class="num">1</span> What to run</h2>

  <div class="line">
    <span class="label">Suite</span>
    <span class="value">
      <button class="pick" aria-expanded={showSuites} onclick={() => (pickSuite = !pickSuite)}>
        {#if suite}<strong>{suite.title}</strong>{:else if draft.scenarios.length}none: your own scenarios{:else}choose a suite{/if} ▾</button>
      {#if suite}
        {#if changes.length}<span class="muted small">modified: {changes.join(", ")}</span>
          <button class="link" onclick={() => useSuite(suite.id)}>Reset</button>{/if}
        <button class="x" onclick={removeSuite} aria-label="Clear the suite" title="Clear the suite (your setups stay)">×</button>
      {:else if !draft.scenarios.length}<span class="muted small">or <button class="link" onclick={() => (pickScenarios = true)}>pick scenarios yourself</button></span>{/if}
    </span>
  </div>
  {#if suite && !showSuites}<p class="muted small hint">{suite.description} Same as <code>uv run arena run {suite.cli}</code>, with your models.</p>{/if}

  {#if showSuites}
    <div class="suites">
      {#each SUITES as s (s.id)}
        {@const count = suiteScenarios(s, app.scenarios).length}
        <button class="card suite" class:current={draft.suite === s.id} onclick={() => useSuite(s.id)}>
          <strong>{s.title}</strong>
          <span class="desc">{s.description}</span>
          <span class="meta">{plural(count, "scenario")}{s.variants ? ` · ${plural(s.variants.length, "variant")}` : ""}{s.swaps ? " · replacement study" : ""}</span>
        </button>
      {/each}
    </div>
  {/if}

  <div class="line">
    <span class="label">Scenarios</span>
    <span class="value chips">
      {#each selected as s (s.id)}
        <span class="chip">{s.title} <span class="muted">{draft.limit && draft.limit < s.tasks ? `${draft.limit} of ${s.tasks}` : s.tasks} tasks</span>
          <button class="x" onclick={() => toggleScenario(s.id)} aria-label={`Remove ${s.title}`}>×</button></span>
      {:else}<span class="muted">none yet</span>{/each}
      <button class="link" onclick={() => (pickScenarios = !pickScenarios)} aria-expanded={pickScenarios}>{pickScenarios ? "Done" : "+ scenario"}</button>
    </span>
  </div>
  {#if pickScenarios}
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
              <span class="meta">{s.tasks} tasks
                {#each (s.wiki ?? []).filter((link) => !EVALUATION_PAGES.has(link.title)) as link (link.url)} · <a href={link.url} target="_blank" rel="noopener" onclick={(e) => e.stopPropagation()}>{link.title}</a>{/each}</span>
            </span>
          </label>
        {/each}
      </div>
    {/each}
  {/if}

  {#if draft.scenarios.length}
    <div class="line">
      <span class="label">Variants</span>
      <span class="value chips">
        {#each variants as v, i (i)}
          <span class="chip" class:editing={editVariant === i}>
            <button class="chip-name" onclick={() => (editVariant = editVariant === i ? null : i)} aria-expanded={editVariant === i}>{v.name || "unnamed"}</button>
            <button class="x" onclick={() => removeVariant(i)} aria-label={`Remove variant ${v.name}`}>×</button></span>
        {:else}<span class="muted">one plain run</span>{/each}
        <button class="link" onclick={addVariant}>+ variant</button>
        {#if !variants.length}<span class="muted small">to compare a parameter or a control policy</span>{/if}
      </span>
    </div>
    {#if editVariant !== null && draft.variants?.[editVariant]}
      <div class="card editor">
        <VariantCard bind:variant={draft.variants[editVariant]!} {selected} />
        <button onclick={() => (editVariant = null)}>Done</button>
      </div>
    {/if}
  {/if}
</section>

<section class="step" aria-labelledby="models-title">
  <h2 id="models-title"><span class="num">2</span> Which models</h2>
    <p class="muted">{draft.configs.length === 1 ? "One setup: the run evaluates it. Add another to compare." : `${draft.configs.length} setups, compared side by side${baseline ? ` and with the baseline ${baseline.name}` : ""}.`}
      A setup has a model per kind of step; click a model to change it.</p>
    <div class="table-wrap">
      <table class="bundles">
        <thead>
          <tr>
            <th scope="col">Setup</th>
            {#each kinds as k (k.kind)}<th scope="col" title={KINDS.find((x) => x.kind === k.kind)?.hint}>{kindLabel(k.kind)}
              {#if k.roles.length}<span class="roles">{k.roles.join(", ")}</span>{/if}</th>{/each}
            <th scope="col"><span class="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {#each draft.configs as config, index (index)}
            {@const models = bundleModels(config, app.presets)}
            {@const exceptions = kindExceptions(config, app.scenarios, draft.scenarios, app.presets)}
            <tr>
              <th scope="row" class="bundle">
                <div class="bundle-head">
                  <strong>{config.name}</strong>
                  {#if config.baseline}<span><span class="badge" title="The report shows every other setup's effect against this one">baseline</span></span>{/if}
                  <span class="muted small">{bundleSource(config, app.presets)}</span>
                  {#if config.swap}
                    {@const origin = draft.configs.find((c) => c.id && c.id === config.swap?.from)}
                    {@const problem = swapProblem(config, draft.configs, selected, app.presets)}
                    <span class="muted small">swaps {config.swap.role} → {describeRef(config.swap.candidate)}{origin ? ` of ${origin.name}` : ""}</span>
                    {#if problem}<span class="small bad">{problem}</span>{/if}
                  {/if}
                  {#if config.only}<span class="muted small">only in {titles(config.only)}</span>{/if}
                  {#if config.decisions}<span class="muted small" title={variants.length ? "Every variant sets the control policy, so this setup's own policy is not used" : ""}>
                    {variants.length ? "own policy: replaced by the variants" : "own control policy"}</span>{/if}
                </div>
              </th>
              {#each kinds as k (k.kind)}
                {@const missing = models[k.kind] ? lacking(catalog, models[k.kind]!, k.needs) : []}
                {@const open = editCell?.index === index && editCell.kind === k.kind}
                <td data-kind={kindLabel(k.kind)}>
                  <button class="cell" class:own={!!config.kinds?.[k.kind]} class:missing={!models[k.kind] || missing.length > 0} class:active={open}
                    aria-expanded={open} title={missing.length ? `${models[k.kind]} lacks ${missing.join(", ")}` : models[k.kind] || "choose a model"}
                    onclick={() => (editCell = open ? null : { index, kind: k.kind })}>
                    <span class="cell-text">{models[k.kind] ? describeRef(models[k.kind]!) : "choose…"}</span><span class="caret" aria-hidden="true">▾</span></button>
                  {#if missing.length}<span class="cell-note bad">lacks {missing.join(", ")}</span>{/if}
                  {#if exceptions[k.kind]?.length}<span class="cell-note" title={differ(exceptions[k.kind]!)}>+{plural(exceptions[k.kind]!.length, "step")} differ{exceptions[k.kind]!.length === 1 ? "s" : ""}</span>{/if}
                </td>
              {/each}
              <td class="actions-cell">
                <button class="icon" onclick={() => (details = details === index ? null : index)} aria-expanded={details === index}
                  aria-label={`More settings for ${config.name}`} title="Name, preset, models per role and per scenario">⋯</button>
                {#if draft.configs.length > 1}<button class="icon" onclick={() => removeBundle(index)} aria-label={`Remove ${config.name}`}>×</button>{/if}
              </td>
            </tr>
            {#if editCell?.index === index}
              {@const kind = editCell.kind}
              {@const needs = kinds.find((k) => k.kind === kind)?.needs ?? []}
              <tr class="sub-row">
                <td colspan={kinds.length + 2}>
                  <div class="cell-editor">
                    <span><strong>{kindLabel(kind)}</strong> model of {config.name}</span>
                    <ModelRefInput id={`cell-${index}-${kind}`} value={config.kinds?.[kind] ?? ""} options={eligibleModels(catalog, needs)}
                      empty={`${bundleSource({ ...config, kinds: {} }, app.presets)}: ${describeRef(splitRef(baseModel(config, kind)).base) || "none"}`}
                      inheritedValue={baseModel(config, kind)} label={`${kindLabel(kind)} model`} onchange={(ref) => setKind(config, kind, ref)} />
                    <button onclick={() => (editCell = null)}>Done</button>
                  </div>
                </td>
              </tr>
            {/if}
            {#if details === index}
              <tr class="sub-row">
                <td colspan={kinds.length + 2}>
                  <ConfigCard bind:config={draft.configs[index]!} {index} {slots} {selected} {decides} onbaseline={(on) => setBaseline(index, on)} />
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
    <div class="add">
      <span class="muted small">Add a setup:</span>
      <select aria-label="Add a setup from a preset" value="" onchange={(e) => { if (e.currentTarget.value) addBundle(configForPreset(e.currentTarget.value)); e.currentTarget.value = ""; }}>
        <option value="">from a preset…</option>
        {#each Object.entries(app.presets) as [name, p] (name)}<option value={name}>{p.label}</option>{/each}
      </select>
      <span class="muted small">or</span>
      <span class="add-model">
        <ModelRefInput id="add-model" bind:value={addModel} options={eligibleModels(catalog, allNeeds)} label="One model for every step"
          empty={`one model for every step${allNeeds.length ? ` (with ${allNeeds.join(", ")})` : ""}…`} thinkingWithModel />
        <button onclick={() => { addBundle(configForModel(addModel)); addModel = ""; }} disabled={!addModel}>Add</button>
      </span>
    </div>
    {#if swapping}
      <SwapPanel configs={draft.configs} {selected} roles={swapRoles} initialRoles={swapping} onadd={addSwaps} onclose={() => (swapping = null)} />
    {:else}
      <p class="muted small">What is one step's model worth? <button class="link" onclick={() => (swapping = [])}>Add swaps</button> of a
        baseline setup: each new setup changes one step, and the report shows its effect against the baseline.</p>
    {/if}
</section>

<section class="step" aria-labelledby="run-title">
  <h2 id="run-title"><span class="num">3</span> How much</h2>
  {#if draft.scenarios.length}
    <p class="plan">
      <span class="muted">{plural(draft.scenarios.length, "scenario")}
        {variants.length ? `× ${plural(variants.length, "variant")}` : ""} × {plural(draft.configs.length, "setup")}
        × {draft.limit ? plural(draft.limit, "task") : "all tasks"} × {plural(draft.repeats || 1, "repeat")}{draft.split !== "all" ? ` (${draft.split} split)` : ""} =</span>
      <strong>{planned.exact ? "" : "up to "}{plural(planned.trials, "trial")}</strong>
      <span class="muted">· spend limit {draft.maxCostUsd ? usd(draft.maxCostUsd) : "none"}</span>
      {#if skipped.length}<span class="muted small skip">A control policy runs only where a scenario supports one, so
        {expandConfigs(draft).some(({ variant }) => variant) ? "variants" : "setups"} with a policy skip {skipped.join(", ")}.</span>{/if}
      {#if draft.configs.some((c) => c.only)}<span class="muted small skip">Swaps run only in the scenarios where they change a step.</span>{/if}
      {#if estimate}
        <span>· ~{estimate.tokens.toLocaleString("en-US")} tokens · ~{usd(estimate.cost_usd)}
          {#if estimate.unknown_prices?.length}<span class="muted"> (no price for {estimate.unknown_prices.join(", ")})</span>{/if}</span>
      {/if}
    </p>
  {:else}
    <p class="muted">Choose a suite or scenarios first.</p>
  {/if}
  <details class="settings-wrap">
    <summary>Run settings</summary>
    <div class="card settings">
      <label>Tasks per scenario (empty = all)<input type="number" min="1" bind:value={draft.limit} /></label>
      <label>Repeats per task<input type="number" min="1" max="10" bind:value={draft.repeats} />
        <span class="muted small">more repeats measure consistency (pass^k)</span></label>
      {#if controllable}
        <label>Task split
          <select bind:value={draft.split}>
            <option value="all">all tasks</option><option value="dev">dev (tune thresholds)</option><option value="test">test (report)</option>
          </select>
        </label>
      {/if}
      <label>Spend limit (USD)<input type="number" min="0" step="0.5" bind:value={draft.maxCostUsd} /></label>
      <label>When a price is unknown<select bind:value={draft.budgetMode}><option value="best_effort">run anyway (best effort)</option><option value="strict">refuse (strict)</option></select></label>
      <label>Judge model
        <ModelSelect bind:value={draft.judge} options={catalog} empty="no judge" label="Judge model" />
        <span class="muted small">rubric scores{openEnded ? ", arena" : ""}</span></label>
      {#if openEnded}<label class="inline"><input type="checkbox" bind:checked={draft.arena} /> Pairwise arena battles (needs a judge)</label>{/if}
      {#if app.runtime?.live_search}<label class="inline"><input type="checkbox" bind:checked={live} /> Allow live web/arXiv search</label>{/if}
    </div>
  </details>

  {#if errors.length}
    <ul class="errors">{#each errors as e (e)}<li>{e}</li>{/each}</ul>
  {/if}
  <div class="actions">
    <button class="primary" onclick={start} disabled={busy || errors.length > 0}>Start run</button>
    <button onclick={runEstimate} disabled={busy || errors.length > 0}>Estimate tokens and cost</button>
    <button onclick={downloadYaml} disabled={!draft.scenarios.length}>Download YAML</button>
  </div>
  {#if message}<p class="note">{message}</p>{/if}
</section>

<style>
  .lead { margin-bottom: 8px; }
  .name-line { margin: 12px 0 0; }
  .step { margin: 24px 0; }
  .step h2 { display: flex; align-items: center; gap: 10px; margin: 0 0 12px; font-size: 18px; }
  .num { width: 26px; height: 26px; display: inline-grid; place-items: center; border-radius: 999px; font-size: 14px;
    background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--accent); font-weight: 700; }
  .line { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 10px; align-items: baseline; margin: 8px 0; font-size: 14px; }
  @media (max-width: 560px) { .line { grid-template-columns: 1fr; gap: 4px; } }
  .label { color: var(--text-secondary); font-weight: 600; font-size: 13px; }
  .value { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .hint { margin: -2px 0 8px 100px; }
  @media (max-width: 560px) { .hint { margin-left: 0; } }
  .pick { font: inherit; }
  .suites { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 8px; margin: 4px 0 12px; }
  .suite { display: grid; gap: 4px; align-content: start; text-align: left; font: inherit; color: var(--text-primary); cursor: pointer; padding: 10px 12px; }
  .suite:hover, .suite:focus-visible { border-color: var(--accent); }
  .suite.current { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
  .suite .desc { color: var(--text-secondary); font-size: 13px; }
  .suite .meta { color: var(--text-muted); font-size: 12px; }
  .chips { font-size: 13px; }
  .chip { display: inline-flex; gap: 4px; align-items: center; border: 1px solid var(--border); border-radius: 999px; padding: 3px 4px 3px 10px; background: var(--surface-2); }
  .chip.editing { border-color: var(--accent); }
  .chip-name { border: 0; background: none; padding: 0; font: inherit; color: var(--text-primary); cursor: pointer; text-decoration: underline dotted; }
  .x, .icon { border: 0; background: none; padding: 0 6px; font-size: 16px; line-height: 1; color: var(--text-secondary); cursor: pointer; }
  .x:hover, .icon:hover { color: var(--text-primary); }
  .editor { display: grid; gap: 10px; justify-items: start; margin: 4px 0 8px; }
  .editor > :global(.variant-card) { width: 100%; }
  h3 { font-size: 14px; margin: 12px 0 6px; }
  .scenarios { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 8px; }
  .scenario { display: flex; gap: 10px; cursor: pointer; }
  .scenario.chosen { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
  .scenario.blocked { opacity: 0.55; cursor: not-allowed; }
  .body { display: flex; flex-direction: column; gap: 4px; font-size: 14px; }
  .body .desc { color: var(--text-secondary); font-size: 13px; }
  .body .meta { color: var(--text-muted); font-size: 12px; }
  .table-wrap { border: 1px solid var(--border); border-radius: var(--radius); overflow-x: auto; background: var(--surface); }
  /* Fixed columns: the setup name gets its own width, model cells share the rest and truncate instead of overflowing. */
  .bundles { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
  .bundles thead th:first-child { width: 170px; }
  .bundles thead th:last-child { width: 64px; }
  .bundles th, .bundles td { padding: 8px 10px; text-align: left; vertical-align: middle; border-bottom: 1px solid var(--border); }
  .bundles tbody tr:last-child > * { border-bottom: 0; }
  .bundles thead th { font-size: 12px; color: var(--text-secondary); font-weight: 600; background: var(--surface-2); }
  .roles { display: block; font-weight: 400; color: var(--text-muted); font-size: 11px; }
  .bundle { font-weight: 400; white-space: normal; }
  .bundle-head { display: grid; gap: 2px; }
  .badge { display: inline-block; font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 999px;
    color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
  .bundle strong { overflow-wrap: anywhere; }
  .cell-note { display: block; margin-top: 3px; font-size: 11px; color: var(--text-muted); cursor: help; }
  .cell-note.bad { color: var(--critical); cursor: default; }
  .bundle .bad { color: var(--critical); }
  .cell { width: 100%; display: flex; gap: 6px; align-items: center; justify-content: space-between; text-align: left; font: inherit;
    padding: 4px 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text-primary);
    cursor: pointer; max-width: 240px; }
  .cell-text { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .caret { flex: none; color: var(--text-muted); font-size: 11px; }
  .cell:hover, .cell:focus-visible, .cell.active { border-color: var(--accent); }
  .cell.own { box-shadow: inset 3px 0 0 var(--accent); background: color-mix(in srgb, var(--accent) 8%, transparent); }
  .cell.missing { color: var(--critical); }
  .actions-cell { white-space: nowrap; text-align: right; width: 1%; }
  .sub-row > td { background: var(--surface-2); }
  .cell-editor { display: grid; grid-template-columns: max-content minmax(0, 1fr) auto; gap: 10px; align-items: center; }
  @media (max-width: 720px) {
    .cell-editor { grid-template-columns: 1fr; }
    .bundles thead { display: none; }
    .bundles, .bundles tbody, .bundles tr, .bundles th, .bundles td { display: block; }
    .bundles tbody tr:not(.sub-row) { border-bottom: 1px solid var(--border); position: relative; }
    .bundles td, .bundles th { border-bottom: 0; padding: 4px 10px; }
    .bundles td[data-kind] { display: grid; grid-template-columns: 70px minmax(0, 1fr); align-items: center; }
    .bundles td[data-kind]::before { content: attr(data-kind); color: var(--text-secondary); font-size: 12px; }
    .bundles td[data-kind] .cell-note { grid-column: 2; }
    .cell { max-width: none; }
    .bundles { table-layout: auto; }
    .actions-cell { position: absolute; top: 6px; right: 4px; width: auto; }
    .bundles th.bundle { padding-right: 72px; }
  }
  .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .add { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 10px; }
  .add-model { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px; flex: 1 1 360px; max-width: 520px; align-items: start; }
  .exp-name { flex: 0 1 280px; min-width: 0; }
  .plan { margin: 0 0 8px; }
  .skip { display: block; margin-top: 2px; }
  .settings-wrap > summary { cursor: pointer; font-weight: 600; font-size: 14px; padding: 4px 0; }
  .settings { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin-top: 8px; }
  .settings label { display: flex; flex-direction: column; gap: 4px; }
  .settings label.inline { flex-direction: row; align-items: center; }
  .errors { color: var(--critical); font-size: 13px; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 12px 0 40px; }
  .link { font-size: 13px; white-space: nowrap; }
</style>
