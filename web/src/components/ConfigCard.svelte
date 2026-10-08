<script lang="ts">
  import { app } from "../lib/app.svelte";
  import {
    DEFAULT_ROLE, defaultRoleNeeds, eligibleModels, knownPreset, policyLabel, withKinds, type ConfigDraft, type RoleSlot,
  } from "../lib/builder";
  import type { ScenarioManifest } from "../lib/contracts";
  import { describeRef, modelFor, splitRef } from "../lib/presets";
  import ModelRefInput from "./ModelRefInput.svelte";
  import ScenarioSetup from "./ScenarioSetup.svelte";

  // A setup's details, edited in place: its name, what it starts from (a preset or one model), a model per role, and
  // per-scenario steps and parameters. Models per kind are edited in the setup table itself.
  let {
    config = $bindable(), index, slots, selected, decides,
  }: { config: ConfigDraft; index: number; slots: RoleSlot[]; selected: ScenarioManifest[]; decides: boolean } = $props();

  const catalog = $derived(app.models?.models ?? []);
  // The setup as it runs: with models of its own per kind, it is a preset of its own.
  const effective = $derived(withKinds(config, app.presets));
  const preset = $derived(knownPreset(effective.config, effective.profiles));
  const ownKinds = $derived(Object.values(config.kinds ?? {}).some(Boolean));

  function kindsFor(slot: RoleSlot): string[] {
    return [...new Set(selected.flatMap((m) => m.roles.filter((r) => r.name === slot.name).map((r) => r.kind ?? "text")))].sort();
  }
  // Decision roles do nothing unless a control policy calls an LLM, so they appear only then.
  const shown = $derived(slots.filter((slot) => !kindsFor(slot).every((k) => k === "decision") || decides));
  function inherited(slot: RoleSlot): string {
    const kinds = kindsFor(slot);
    if (preset && kinds.length === 1) return modelFor(effective.profiles[preset], kinds[0]!);
    if (!preset) return config.roles[DEFAULT_ROLE] ?? "";
    return "";
  }
  // The "" choice names where the model comes from; its thinking shows in the thinking select next to it.
  function emptyLabel(slot: RoleSlot): string {
    const model = describeRef(splitRef(inherited(slot)).base);
    if (preset) return `${ownKinds ? "this setup" : app.presets[preset]?.label ?? preset}: ${model || "by step kind"}`;
    if (model) return `the setup's model (${model})`;
    return slot.optional ? "same as its fallback step" : "choose a model";
  }
  function roleNote(slot: RoleSlot): string {
    const kinds = kindsFor(slot);
    const kind = kinds.length === 1 ? kinds[0] : `${kinds.length} kinds`;
    return [kind === slot.name ? "" : kind, slot.needs.length ? `needs ${slot.needs.join(", ")}` : ""].filter(Boolean).join(" · ");
  }
  function setRole(role: string, ref: string) {
    config.roles = { ...config.roles, [role]: ref };
    if (!ref) delete config.roles[role];
  }
  function setBase(value: string) {
    // "" = one model for every step; the per-kind models the user set stay on top of either.
    config.preset = value;
    if (value) config.roles = { ...config.roles, [DEFAULT_ROLE]: "" };
  }
</script>

<div class="config-card">
  <div class="row">
    <label class="label" for={`config-name-${index}`}>Name</label>
    <span class="name">
      <input id={`config-name-${index}`} type="text" value={config.name} title={config.named ? "" : "Named after its models until you type a name"}
        oninput={(e) => { config.name = e.currentTarget.value; config.named = true; }} />
      {#if config.named}<button class="link" onclick={() => (config.named = false)} title="Name it after its models again">↺ auto name</button>{/if}
    </span>
  </div>
  <div class="row">
    <label class="label" for={`config-base-${index}`}>Starts from <a class="small" href="#/presets">presets</a></label>
    <select id={`config-base-${index}`} value={knownPreset(config, app.presets)} onchange={(e) => setBase(e.currentTarget.value)}>
      <option value="">one model for every step</option>
      {#each Object.entries(app.presets) as [name, p] (name)}<option value={name}>{p.label} preset</option>{/each}
    </select>
  </div>
  {#if !knownPreset(config, app.presets)}
    <div class="row">
      <span class="label">Model</span>
      <ModelRefInput id={`config-model-${index}`} bind:value={config.roles[DEFAULT_ROLE]} options={eligibleModels(catalog, defaultRoleNeeds(slots, config))} label="Model" />
    </div>
  {/if}

  {#if shown.length}
    <fieldset>
      <legend>Per role <span class="muted small">leave as is to use the setup's model for the role's kind</span></legend>
      {#each shown as slot (slot.name)}
        <div class="row">
          <span class="label"><strong>{slot.name}</strong> <span class="muted small">{roleNote(slot)}</span></span>
          <ModelRefInput id={`config-${index}-${slot.name}`} value={config.roles[slot.name] ?? ""} options={eligibleModels(catalog, slot.needs)}
            empty={emptyLabel(slot)} inheritedValue={inherited(slot)} label={`Model for ${slot.name}`} onchange={(ref) => setRole(slot.name, ref)} />
        </div>
      {/each}
    </fieldset>
  {/if}

  {#if config.decisions}
    <p class="small policy">This setup brings its own control policy ({policyLabel(config.decisions)}, {config.decisions.control ?? "policy"}),
      used when the experiment has no variants.
      <button class="link" onclick={() => (config.decisions = null)}>Remove it</button></p>
  {/if}

  {#if selected.length}
    <details class="per-scenario">
      <summary>Per scenario: steps and parameters</summary>
      {#each selected as s (s.id)}
        <details class="scenario-setup" open={selected.length === 1}>
          <summary><strong>{s.title}</strong></summary>
          <ScenarioSetup manifest={s} bind:config showDefault={false} showPreset={false} />
        </details>
      {/each}
    </details>
  {/if}
</div>

<style>
  .config-card { display: grid; gap: 10px; }
  .row { display: grid; grid-template-columns: minmax(160px, 0.8fr) minmax(220px, 1.2fr); gap: 10px; align-items: center; font-size: 14px; }
  @media (max-width: 720px) { .row { grid-template-columns: 1fr; } }
  .label strong { margin-right: 4px; }
  .name { display: flex; gap: 8px; align-items: center; }
  .name input { font-weight: 600; min-width: 0; flex: 1; }
  fieldset { min-width: 0; border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 12px 10px; margin: 0; display: grid; gap: 6px; }
  legend { font-weight: 600; font-size: 13px; padding: 0 4px; }
  .policy { margin: 0; }
  .per-scenario > summary { cursor: pointer; font-weight: 600; font-size: 13px; }
  .scenario-setup { margin-top: 10px; border-top: 1px solid var(--border); padding-top: 8px; }
  .scenario-setup summary { cursor: pointer; margin-bottom: 8px; }
  .link { font-size: 13px; white-space: nowrap; }
</style>
