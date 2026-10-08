<script lang="ts">
  import { app } from "../lib/app.svelte";
  import { CONTROLS, POLICIES, SERVICE_LABELS, llmRoles, servicesUsed, type Service, type VariantDraft } from "../lib/builder";
  import type { ParamManifest, ScenarioManifest } from "../lib/contracts";

  // One way of running the selected scenarios: parameters (applied to every scenario that has them) and, where a
  // scenario supports one, a control policy. Every setup runs it.
  let { variant = $bindable(), selected }: { variant: VariantDraft; selected: ScenarioManifest[] } = $props();

  const services = $derived(app.runtime?.decision_services ?? {});
  const available = (service: string) => services[service]?.status === "available";
  const SERVICES_SHOWN: Service[] = ["jev", "ollaya"];
  // An unavailable service says why in its own (disabled) option, and next to the policy only when the policy uses it.
  const unavailable = (service: string) => (SERVICES_SHOWN as string[]).includes(service) && !available(service);
  const why = (service: string) => (unavailable(service) ? ` (${services[service]?.status ?? "unknown"})` : "");
  const controllable = $derived(selected.filter((m) => m.supports_decisions));
  // Parameters by name across the selected scenarios, with the scenarios that have each.
  const params = $derived.by(() => {
    const byName = new Map<string, { param: ParamManifest; scenarios: string[] }>();
    for (const m of selected) for (const p of m.params) {
      const entry = byName.get(p.name) ?? { param: p, scenarios: [] };
      entry.scenarios.push(m.title);
      byName.set(p.name, entry);
    }
    return [...byName.values()];
  });

  function setParam(param: ParamManifest, raw: string) {
    const next = { ...variant.params };
    if (raw === "") delete next[param.name];
    else next[param.name] = param.type === "boolean" ? raw === "true" : param.type === "integer" ? parseInt(raw, 10)
      : param.type === "number" ? parseFloat(raw) : raw;
    variant.params = next;
  }
  function setPolicy(value: string) {
    const base = variant.decisions ?? { control: "gate", threshold: 0.8, ollaya_model: services.ollaya?.models?.[0] ?? "winnow:e4b" };
    variant.decisions = value ? { ...base, policy: value as never } : null;
  }
  const shown = (value: unknown) => (value === undefined ? "" : String(value));
</script>

<div class="variant-card">
  <label class="field">Name <input type="text" bind:value={variant.name} /></label>
  {#if params.length}
    <fieldset>
      <legend>Parameters <span class="muted small">empty = the scenario's default</span></legend>
      {#each params as { param, scenarios } (param.name)}
        <label class="field">
          <span>{param.name} <span class="muted small">{scenarios.join(", ")}</span></span>
          {#if param.choices || param.type === "boolean"}
            <select value={shown(variant.params[param.name])} onchange={(e) => setParam(param, e.currentTarget.value)}>
              <option value="">default ({String(param.default)})</option>
              {#each param.choices ?? [true, false] as choice (String(choice))}<option value={String(choice)}>{String(choice)}</option>{/each}
            </select>
          {:else}
            <input type={param.type === "integer" || param.type === "number" ? "number" : "text"} min="0" placeholder={`default (${String(param.default)})`}
              value={shown(variant.params[param.name])} onchange={(e) => setParam(param, e.currentTarget.value)} />
          {/if}
        </label>
      {/each}
    </fieldset>
  {/if}
  {#if controllable.length}
    <fieldset class="policy">
      <legend>Control policy <span class="muted small">{controllable.map((m) => m.title).join(", ")}</span></legend>
      <label class="param">who decides
        <select value={variant.decisions?.policy ?? ""} onchange={(e) => setPolicy(e.currentTarget.value)}>
          <option value="">the agent itself</option>
          {#each POLICIES as p (p.value)}<option value={p.value} disabled={unavailable(p.value)}>{p.label}{why(p.value)}</option>{/each}
        </select>
      </label>
      {#if variant.decisions}
        <label class="param">mode
          <select bind:value={variant.decisions.control}>{#each CONTROLS as c (c.value)}<option value={c.value}>{c.label}</option>{/each}</select>
        </label>
        {#if variant.decisions.policy === "cascade"}
          <label class="param">primary
            <select bind:value={variant.decisions.primary}><option value="llm">LLM (decider)</option><option value="jev" disabled={unavailable("jev")}>Jev{why("jev")}</option><option value="ollaya" disabled={unavailable("ollaya")}>Ollaya{why("ollaya")}</option></select>
          </label>
          <label class="param">fallback
            <select bind:value={variant.decisions.fallback}><option value="llm">LLM (escalation)</option><option value="jev" disabled={unavailable("jev")}>Jev{why("jev")}</option><option value="ollaya" disabled={unavailable("ollaya")}>Ollaya{why("ollaya")}</option><option value={null}>none</option></select>
          </label>
          <label class="param">escalate below<input type="number" min="0" max="1" step="0.05" bind:value={variant.decisions.threshold} /></label>
        {/if}
        {#if servicesUsed(variant.decisions).includes("ollaya")}
          <label class="param">Ollaya model
            <select bind:value={variant.decisions.ollaya_model}>{#each services.ollaya?.models ?? ["winnow:e4b"] as m (m)}<option value={m}>{m}</option>{/each}</select>
          </label>
        {/if}
        {#each servicesUsed(variant.decisions).filter(unavailable) as s (s)}
          <span class="small unavailable">{SERVICE_LABELS[s]}: {services[s]?.status ?? "unknown"}</span>
        {/each}
        {#if llmRoles(variant.decisions).length}<p class="muted small policy-note">The LLM steps run on each setup's decision model.</p>{/if}
      {/if}
    </fieldset>
  {/if}
  {#if !params.length && !controllable.length}<p class="muted small">The selected scenarios have no parameters or control policy to vary.</p>{/if}
</div>

<style>
  .variant-card { display: grid; gap: 10px; }
  .field { display: grid; grid-template-columns: minmax(160px, 0.8fr) minmax(200px, 1.2fr); gap: 10px; align-items: center; font-size: 13px; }
  @media (max-width: 640px) { .field { grid-template-columns: 1fr; } }
  fieldset { min-width: 0; border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 12px 10px; margin: 0; display: grid; gap: 6px; }
  legend { font-weight: 600; font-size: 13px; padding: 0 4px; }
  .policy { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; font-size: 13px; }
  .param { display: flex; gap: 6px; align-items: center; min-width: 0; max-width: 100%; }
  .param select { min-width: 0; flex: 1 1 auto; }
  .param input[type="number"] { width: 70px; }
  .unavailable { color: var(--critical); }
  .policy-note { margin: 0; flex-basis: 100%; }
</style>
