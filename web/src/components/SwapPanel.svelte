<script lang="ts">
  import { untrack } from "svelte";
  import { app } from "../lib/app.svelte";
  import { swapSetups, type ConfigDraft } from "../lib/builder";
  import type { ScenarioManifest } from "../lib/contracts";
  import { describeRef } from "../lib/presets";
  import ModelRefInput from "./ModelRefInput.svelte";

  // A replacement study as setups: pick the baseline, candidate models and the steps to swap; each new setup copies
  // the baseline and swaps one step to one candidate, only where that changes something. Swaps a candidate cannot do
  // are listed, not silently dropped.
  let {
    configs, selected, roles, initialRoles = [], onadd, onclose,
  }: {
    configs: ConfigDraft[]; selected: ScenarioManifest[]; roles: string[]; initialRoles?: string[];
    onadd: (baseline: number, setups: ConfigDraft[]) => void; onclose: () => void;
  } = $props();

  const catalog = $derived(app.models?.models ?? []);
  // Starting choices, read once: the marked baseline (else the first setup) and the suite's steps (else every step).
  let base = $state(untrack(() => Math.max(0, configs.findIndex((c) => c.baseline))));
  let candidates = $state<string[]>([""]);
  let chosen = $state<string[]>(untrack(() => (initialRoles.length ? [...initialRoles] : [...roles])));

  const plan = $derived(configs[base] ? swapSetups(configs[base]!, candidates, chosen, selected, app.presets, catalog) : { setups: [], skipped: [] });
  const titles = (ids: string[] = []) => ids.map((id) => selected.find((m) => m.id === id)?.title ?? id).join(", ");
  const kindsOf = (role: string) => [...new Set(selected.flatMap((m) => m.roles.filter((r) => r.name === role).map((r) => r.kind ?? "text")))].join(", ");

  function toggle(role: string) {
    chosen = chosen.includes(role) ? chosen.filter((r) => r !== role) : [...chosen, role];
  }
</script>

<section class="card swap-panel" aria-labelledby="swap-title">
  <h3 id="swap-title">Add swaps</h3>
  <p class="muted small">Each new setup copies the baseline and swaps one step to one candidate model. The report shows its
    effect against the baseline on the tasks both ran.</p>

  <div class="row">
    <label class="label" for="swap-base">Baseline</label>
    <select id="swap-base" bind:value={base}>
      {#each configs as c, i (i)}<option value={i}>{c.name}</option>{/each}
    </select>
  </div>

  <fieldset>
    <legend>Candidate models</legend>
    {#each candidates as _, i (i)}
      <div class="candidate">
        <ModelRefInput id={`swap-candidate-${i}`} bind:value={candidates[i]} options={catalog} label={`Candidate ${i + 1}`} empty="choose a model…" thinkingWithModel />
        {#if candidates.length > 1}<button onclick={() => (candidates = candidates.filter((_, j) => j !== i))} aria-label={`Remove candidate ${i + 1}`}>Remove</button>{/if}
      </div>
    {/each}
    <button class="link" onclick={() => (candidates = [...candidates, ""])}>+ candidate</button>
  </fieldset>

  <fieldset>
    <legend>Steps to swap</legend>
    {#if !roles.length}<p class="muted small">Select scenarios first.</p>{/if}
    <div class="roles">
      {#each roles as role (role)}
        <label class="role"><input type="checkbox" checked={chosen.includes(role)} onchange={() => toggle(role)} />
          <strong>{role}</strong> <span class="muted small">{kindsOf(role)}</span></label>
      {/each}
    </div>
  </fieldset>

  <div class="preview" aria-live="polite">
    {#if plan.setups.length}
      <p class="small"><strong>Adds {plan.setups.length} setup{plan.setups.length === 1 ? "" : "s"}</strong></p>
      <ul>{#each plan.setups as s (s.name)}<li><strong>{s.name}</strong> <span class="muted small">only in {titles(s.only)}</span></li>{/each}</ul>
    {:else}
      <p class="muted small">Choose a candidate model and at least one step it can swap.</p>
    {/if}
    {#if plan.skipped.length}
      <p class="small skipped-title">Skipped</p>
      <ul class="skipped">{#each plan.skipped as k (`${k.candidate}|${k.role}|${k.scenario}`)}
        <li class="small">{describeRef(k.candidate)} as {k.role} in {k.scenario}: {k.why}</li>{/each}</ul>
    {/if}
  </div>

  <div class="actions">
    <button class="primary" disabled={!plan.setups.length} onclick={() => onadd(base, plan.setups)}>
      Add {plan.setups.length || ""} setup{plan.setups.length === 1 ? "" : "s"}</button>
    <button onclick={onclose}>Cancel</button>
  </div>
</section>

<style>
  .swap-panel { display: grid; gap: 10px; margin-top: 10px; }
  h3 { margin: 0; font-size: 15px; }
  p { margin: 0; }
  .row { display: grid; grid-template-columns: 90px minmax(0, 320px); gap: 10px; align-items: center; font-size: 14px; }
  .label { color: var(--text-secondary); font-weight: 600; font-size: 13px; }
  fieldset { min-width: 0; border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 12px 10px; margin: 0; display: grid; gap: 6px; justify-items: start; }
  legend { font-weight: 600; font-size: 13px; padding: 0 4px; }
  .candidate { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px; width: min(100%, 560px); align-items: start; }
  .roles { display: flex; flex-wrap: wrap; gap: 6px 16px; }
  .role { display: flex; gap: 6px; align-items: center; font-size: 14px; }
  .preview ul { margin: 4px 0 0; padding-left: 18px; display: grid; gap: 2px; font-size: 13px; }
  .skipped-title { margin-top: 8px; color: var(--text-secondary); font-weight: 600; }
  .skipped { color: var(--text-secondary); }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; }
  .link { font-size: 13px; }
  @media (max-width: 560px) { .row { grid-template-columns: 1fr; gap: 4px; } }
</style>
