<script lang="ts">
  import { app } from "../lib/app.svelte";
  import { describeRef, modelFor } from "../lib/presets";
  import { CONTROLS, DEFAULT_ROLE, POLICIES, eligibleModels, llmRoles, policyLabel, servicesUsed, type ConfigDraft } from "../lib/builder";
  import type { ParamManifest, ScenarioManifest } from "../lib/contracts";
  import { CONTROL_PARAM, REVIEW_PARAM, resolve, stepRoles } from "../lib/workflow";
  import ModelSelect from "./ModelSelect.svelte";
  import WorkflowDiagram from "./WorkflowDiagram.svelte";

  // Edits `config` in place: per-step models in config.scenarioRoles[id], parameters in config.scenarioParams[id],
  // and (with showPolicy) the control policy in config.decisions.
  let {
    manifest, config = $bindable(), showPolicy = false, showDefault = true, showPreset = true,
  }: { manifest: ScenarioManifest; config: ConfigDraft; showPolicy?: boolean; showDefault?: boolean; showPreset?: boolean } = $props();

  const catalog = $derived(app.models?.models ?? []);
  const services = $derived(app.runtime?.decision_services ?? {});
  const available = (service: string) => services[service]?.status === "available";
  let highlight = $state("");

  const params: Record<string, unknown> = $derived({
    ...Object.fromEntries(manifest.params.map((p) => [p.name, p.default])),
    ...(config.scenarioParams[manifest.id] ?? {}),
    [CONTROL_PARAM]: config.decisions?.control ?? "agent",
    [REVIEW_PARAM]: config.decisions?.review ?? true,
  });
  const flow = $derived(manifest.workflow ? resolve(manifest.workflow, params) : null);
  const policyRoles = $derived(new Set(["decider", "escalation"]));
  // Roles that run in this variant; decision roles only when the policy calls an LLM.
  const activeRoles = $derived(
    manifest.roles.filter((r) =>
      policyRoles.has(r.name) ? llmRoles(config.decisions).includes(r.name) : flow?.steps.some((s) => stepRoles(s).includes(r.name)) ?? true),
  );
  const stepsOf = (role: string) => (flow?.steps ?? []).filter((s) => stepRoles(s).includes(role)).map((s) => s.label);

  const profile = $derived(config.preset ? app.presets[config.preset] : undefined);
  // Steps set explicitly keep their model whatever the preset says (e.g. every step of a setup loaded from the leaderboard).
  const pinned = $derived(Object.entries(config.scenarioRoles[manifest.id] ?? {}).filter(([, ref]) => ref).map(([role]) => role));
  const unpin = () => (config.scenarioRoles = { ...config.scenarioRoles, [manifest.id]: {} });
  // Mirrors the runner: explicit binding > preset by kind > fallback role > default model.
  function effective(role: string, seen = new Set<string>()): string {
    const bound = config.scenarioRoles[manifest.id]?.[role] || config.roles[role];
    if (bound) return bound;
    const requirement = manifest.roles.find((r) => r.name === role);
    if (profile) return modelFor(profile, requirement?.kind ?? "text");
    const fallback = requirement?.fallback;
    if (fallback && !seen.has(fallback)) return effective(fallback, new Set([...seen, role]));
    return config.roles[DEFAULT_ROLE] || "";
  }
  function inherited(role: { name: string; kind?: string; fallback?: string | null }): string {
    if (profile) return `${profile.label}: ${describeRef(modelFor(profile, role.kind ?? "text"))}`;
    if (role.fallback) return `same as ${role.fallback} (${describeRef(effective(role.fallback)) || "—"})`;
    return `default (${describeRef(config.roles[DEFAULT_ROLE] ?? "") || "—"})`;
  }
  // The profile's dedicated decision model ("ollaya:winnow:e4b"), offered as a one-click control policy.
  const service = $derived(profile?.decision_service ? { kind: profile.decision_service.split(":")[0]!, model: profile.decision_service.split(":").slice(1).join(":") } : null);
  function useService() {
    if (!service) return;
    const base = config.decisions ?? { control: "policy", threshold: 0.8, review: true };
    config.decisions = service.kind === "ollaya"
      ? { ...base, policy: "ollaya", ollaya_model: service.model }
      : { ...base, policy: "jev", jev_model: service.model };
  }
  const models = $derived(
    Object.fromEntries(manifest.roles.map((r) => [r.name,
      policyRoles.has(r.name) && config.decisions && !llmRoles(config.decisions).includes(r.name)
        ? policyLabel(config.decisions) : describeRef(effective(r.name)) || "choose a model"])),
  );

  function roles(): Record<string, string> {
    config.scenarioRoles = { ...config.scenarioRoles, [manifest.id]: { ...(config.scenarioRoles[manifest.id] ?? {}) } };
    return config.scenarioRoles[manifest.id]!;
  }
  function setParam(param: ParamManifest, raw: string | boolean) {
    const value = param.type === "boolean" ? Boolean(raw) : param.type === "integer" ? parseInt(String(raw), 10)
      : param.type === "number" ? parseFloat(String(raw)) : raw;
    const current = { ...(config.scenarioParams[manifest.id] ?? {}) };
    if (value === param.default || (typeof value === "number" && Number.isNaN(value))) delete current[param.name];
    else current[param.name] = value;
    config.scenarioParams = { ...config.scenarioParams, [manifest.id]: current };
  }
  function setPolicy(value: string) {
    const base = config.decisions ?? { control: "policy", threshold: 0.8, review: true, ollaya_model: services.ollaya?.models?.[0] ?? "winnow:e4b" };
    config.decisions = value ? { ...base, policy: value as never } : null;
  }
</script>

<div class="setup">
  <div class="controls">
    {#if manifest.params.length}
      <fieldset>
        <legend>Parameters</legend>
        {#each manifest.params as p (p.name)}
          <label class="param">{p.name}
            {#if p.choices}
              <select value={String(params[p.name])} onchange={(e) => setParam(p, e.currentTarget.value)}>
                {#each p.choices as choice (choice)}<option value={String(choice)}>{choice}</option>{/each}
              </select>
            {:else if p.type === "boolean"}
              <input type="checkbox" checked={Boolean(params[p.name])} onchange={(e) => setParam(p, e.currentTarget.checked)} />
            {:else if p.type === "integer" || p.type === "number"}
              <input type="number" min="0" value={params[p.name] === null ? "" : String(params[p.name])} onchange={(e) => setParam(p, e.currentTarget.value)} />
            {:else}
              <input type="text" value={String(params[p.name] ?? "")} onchange={(e) => setParam(p, e.currentTarget.value)} />
            {/if}
          </label>
        {/each}
      </fieldset>
    {/if}

    {#if showPolicy && manifest.supports_decisions}
      <fieldset>
        <legend>Control policy</legend>
        <label class="param">who decides
          <select value={config.decisions?.policy ?? ""} onchange={(e) => setPolicy(e.currentTarget.value)}>
            <option value="">the agent itself</option>
            {#each POLICIES as p (p.value)}<option value={p.value} disabled={(p.value === "jev" || p.value === "ollaya") && !available(p.value)}>{p.label}</option>{/each}
          </select>
        </label>
        {#if service && manifest.supports_decisions && !(config.decisions?.policy === service.kind && (config.decisions?.ollaya_model === service.model || config.decisions?.jev_model === service.model))}
          <button class="link" onclick={useService}>Use the preset's decision model ({service.model})</button>
        {/if}
        {#if config.decisions}
          <label class="param">mode
            <select bind:value={config.decisions.control}>{#each CONTROLS as c (c.value)}<option value={c.value}>{c.label}</option>{/each}</select>
          </label>
          {#if config.decisions.policy === "cascade"}
            <label class="param">primary
              <select bind:value={config.decisions.primary}><option value="llm">LLM (decider)</option><option value="ollaya" disabled={!available("ollaya")}>Ollaya</option><option value="jev" disabled={!available("jev")}>Jev</option></select>
            </label>
            <label class="param">fallback
              <select bind:value={config.decisions.fallback}><option value="llm">LLM (escalation)</option><option value="ollaya" disabled={!available("ollaya")}>Ollaya</option><option value="jev" disabled={!available("jev")}>Jev</option><option value={null}>none</option></select>
            </label>
            <label class="param">escalate below<input type="number" min="0" max="1" step="0.05" bind:value={config.decisions.threshold} /></label>
          {/if}
          {#if servicesUsed(config.decisions).includes("ollaya")}
            <label class="param">Ollaya model
              <select bind:value={config.decisions.ollaya_model}>{#each services.ollaya?.models ?? ["winnow:e4b"] as m (m)}<option value={m}>{m}</option>{/each}</select>
            </label>
          {/if}
          <label class="param"><input type="checkbox" bind:checked={config.decisions.review} /> review the finished trace</label>
        {/if}
      </fieldset>
    {/if}

    <fieldset>
      <legend>Models per step</legend>
      {#if showPreset}
      <div class="role preset">
        <label for={`${manifest.id}-preset`}><strong>Start from preset</strong> <span class="muted">a preset gives each step a model by the kind of work it does</span></label>
        <select id={`${manifest.id}-preset`} bind:value={config.preset}>
          <option value="">no preset: choose models below</option>
          {#each Object.entries(app.presets) as [name, p] (name)}<option value={name}>{p.label}</option>{/each}
        </select>
        {#if profile && pinned.length}
          <p class="note small" role="status">{pinned.length === 1 ? `${pinned[0]} is` : `${pinned.length} steps are`} set below and keep
            {pinned.length === 1 ? "its model" : "their models"}; the preset only fills the others.
            <button class="link" onclick={unpin}>Use the preset for every step</button></p>
        {/if}
        {#if profile}<a class="small" href="#/presets">Edit presets</a>{/if}
      </div>
      {/if}
      {#if showDefault && !profile}
        <div class="role">
          <span><strong>default</strong> <span class="muted">every step not set below</span></span>
          <ModelSelect bind:value={config.roles[DEFAULT_ROLE]} options={catalog} empty="— choose —" label="Default model" />
        </div>
      {/if}
      {#each activeRoles as r (r.name)}
        <div class="role" class:lit={highlight === r.name} role="group" aria-label={`Model for ${r.name}`}
          onmouseenter={() => (highlight = r.name)} onmouseleave={() => (highlight = "")}>
          <span><strong>{r.name}</strong> <span class="pill kind">{r.kind ?? "text"}</span>{#if (r.needs ?? []).length} <span class="pill">needs {r.needs?.join(", ")}</span>{/if}
            <span class="muted small">{stepsOf(r.name).join(" · ") || r.description}</span></span>
          <ModelSelect value={config.scenarioRoles[manifest.id]?.[r.name] ?? ""} options={eligibleModels(catalog, r.needs ?? [])}
            empty={inherited(r)}
            label={`Model for ${r.name}`} onchange={(ref) => (roles()[r.name] = ref)} />
        </div>
      {/each}
    </fieldset>
  </div>

  {#if flow}
    <div class="diagram card">
      <WorkflowDiagram {flow} {models} bind:highlight label={`${manifest.title} workflow`} />
      <p class="muted small legend">
        <span class="k llm"></span>model <span class="k tool"></span>tools <span class="k code"></span>sandbox
        <span class="k decision"></span>control decision <span class="k human"></span>human <span class="k check"></span>check ·
        dashed arrows loop back. Hover a step or a role to see where each model runs.
      </p>
    </div>
  {/if}
</div>

<style>
  .setup { display: grid; grid-template-columns: minmax(280px, 1fr) minmax(320px, 1.3fr); gap: 16px; align-items: start; }
  @media (max-width: 900px) { .setup { grid-template-columns: minmax(0, 1fr); } }
  fieldset { min-width: 0; border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 12px; margin: 0 0 12px; display: grid; gap: 8px; }
  legend { font-weight: 600; font-size: 13px; padding: 0 4px; }
  .param { display: flex; gap: 8px; align-items: center; justify-content: space-between; font-size: 13px; }
  .param input[type="number"] { width: 90px; }
  .param select { flex: 0 1 auto; min-width: 0; max-width: 62%; }
  .role { display: grid; gap: 4px; padding: 6px; border-radius: 8px; font-size: 13px; }
  .role span { display: flex; gap: 6px; flex-wrap: wrap; align-items: baseline; }
  .role.lit { background: var(--surface-2); }
  .role.preset { border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 4px; }
  .role.preset select { width: 100%; }
  .kind { font-size: 11px; }
  .link { background: none; border: none; color: var(--accent); padding: 0; text-decoration: underline; cursor: pointer; font-size: 13px; justify-self: start; }
  .role :global(select) { width: 100%; min-width: 0; }
  .small { font-size: 12px; }
  .diagram { padding: 12px; position: sticky; top: 64px; }
  .legend { margin: 8px 0 0; }
  .k { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 3px 0 8px; vertical-align: -1px; }
  .k.llm { background: var(--accent); } .k.tool { background: var(--kind-tool); } .k.code { background: var(--kind-code); }
  .k.decision { background: var(--kind-decision); } .k.human { background: var(--kind-human); } .k.check { background: var(--kind-check); }
</style>
