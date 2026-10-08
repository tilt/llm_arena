<script lang="ts">
  import { app } from "../lib/app.svelte";
  import { describeRef, modelFor } from "../lib/presets";
  import { studyConfigs, type StudyDraft } from "../lib/builder";
  import type { ScenarioManifest } from "../lib/contracts";
  import ModelRefInput from "./ModelRefInput.svelte";

  // A replacement study: the baseline, the candidate models, and which steps to swap. The preview lists exactly the
  // configurations that will run (baseline + one per swapped step and candidate).
  let { study = $bindable(), manifests }: { study: StudyDraft; manifests: ScenarioManifest[] } = $props();

  const catalog = $derived(app.models?.models ?? []);
  const profile = $derived(app.presets[study.baseline]);
  const controlled = $derived(manifests.some((m) => m.supports_decisions));
  const services = $derived([
    ...(app.runtime?.decision_services?.ollaya?.models ?? []).map((m) => ({ ref: `ollaya:${m}`, label: `winnow and co. via Ollaya: ${m}` })),
    ...(app.runtime?.decision_services?.jev?.status === "available" ? [{ ref: "jev:jev-latest", label: "Jev (TypeSafe)" }] : []),
  ]);
  const modelCandidates = $derived(study.candidates.map((c, i) => ({ c, i })).filter(({ c }) => !c.startsWith("ollaya:") && !c.startsWith("jev:")));
  const roles = $derived.by(() => {
    const byName = new Map<string, { name: string; kind: string; scenarios: string[] }>();
    for (const m of manifests) for (const r of m.roles) {
      const entry = byName.get(r.name) ?? { name: r.name, kind: r.kind ?? "text", scenarios: [] };
      entry.scenarios.push(m.title);
      byName.set(r.name, entry);
    }
    return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name));
  });
  const chosen = (role: { name: string; kind: string }) => (study.roles.length ? study.roles.includes(role.name) : role.kind !== "decision");
  function toggleRole(role: { name: string; kind: string }) {
    const current = roles.filter((r) => chosen(r)).map((r) => r.name);
    study.roles = chosen(role) ? current.filter((n) => n !== role.name) : [...current, role.name];
  }
  function toggleService(ref: string) {
    study.candidates = study.candidates.includes(ref) ? study.candidates.filter((c) => c !== ref) : [...study.candidates, ref];
  }
  // Mirrors the engine: a candidate replaces only steps whose needs (e.g. vision) it meets.
  const canDo = (candidate: string, needs: string[]) => {
    const found = catalog.find((m) => m.ref === candidate.split("#")[0]);
    const capabilities = (found?.spec.capabilities ?? {}) as Record<string, unknown>;
    return needs.every((need) => (found ? Boolean(capabilities[need]) : need !== "vision"));
  };
  const preview = $derived(studyConfigs(study, manifests, profile, canDo));
</script>

<div class="study">
  <section class="card">
    <h3>Baseline</h3>
    <p class="muted">Every configuration starts from this preset; only one step changes at a time.</p>
    <select bind:value={study.baseline} aria-label="Baseline preset">
      {#each Object.entries(app.presets) as [name, p] (name)}<option value={name}>{p.label}</option>{/each}
    </select>
    {#if profile}<p class="muted small">{profile.description} <a href="#/presets">Edit presets</a></p>{/if}
  </section>

  <section class="card">
    <h3>Candidate models</h3>
    <p class="muted">Each candidate replaces the baseline model of one step at a time.</p>
    {#each modelCandidates as { i } (i)}
      <div class="candidate">
        <ModelRefInput id={`candidate-${i}`} bind:value={study.candidates[i]!} options={catalog} label={`Candidate ${i + 1}`} />
        <button onclick={() => (study.candidates = study.candidates.filter((_, j) => j !== i))} aria-label={`Remove candidate ${i + 1}`}>Remove</button>
      </div>
    {/each}
    <button onclick={() => (study.candidates = [...study.candidates, ""])}>+ Add a candidate model</button>
    {#if controlled && services.length}
      <fieldset>
        <legend>Dedicated decision models <span class="muted">(replace the control decisions of scenarios that have them)</span></legend>
        {#each services as s (s.ref)}
          <label class="check"><input type="checkbox" checked={study.candidates.includes(s.ref)} onchange={() => toggleService(s.ref)} /> {s.label}</label>
        {/each}
        {#if study.candidates.some((c) => c.startsWith("ollaya:") || c.startsWith("jev:"))}
          <label class="check">decisions control
            <select bind:value={study.decisionControl}>
              <option value="gate">gate risky actions</option><option value="policy">run the loop</option><option value="review">review the trace</option>
            </select></label>
        {/if}
      </fieldset>
    {/if}
  </section>

  <section class="card">
    <h3>Steps to swap</h3>
    {#if !roles.length}<p class="muted">Select scenarios first.</p>{/if}
    <div class="roles">
      {#each roles as role (role.name)}
        <label class="role">
          <input type="checkbox" checked={chosen(role)} onchange={() => toggleRole(role)} />
          <span><strong>{role.name}</strong> <span class="pill">{role.kind}</span>
            <span class="muted small">baseline: {describeRef(modelFor(profile, role.kind)) || "—"} · {role.scenarios.join(", ")}</span></span>
        </label>
      {/each}
    </div>
    {#if roles.some((r) => r.kind === "decision")}<p class="muted small">Decision roles matter only with an LLM control policy; use a dedicated decision model above instead.</p>{/if}
  </section>

  <section class="card preview" aria-live="polite">
    <h3>Configurations <span class="count">{preview.length}</span></h3>
    <ul>
      {#each preview as c (c.name)}<li><strong>{c.name}</strong> <span class="muted small">{c.scenarios.join(", ")}</span></li>{/each}
    </ul>
    {#if preview.length < 2}<p class="muted small">Add a candidate model that differs from the baseline.</p>{/if}
  </section>
</div>

<style>
  .study { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
  .study .card { display: grid; gap: 8px; align-content: start; }
  h3 { margin: 0; font-size: 15px; }
  p { margin: 0; }
  .candidate { display: grid; grid-template-columns: 1fr auto; gap: 6px; }
  fieldset { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; display: grid; gap: 6px; }
  legend { font-size: 13px; }
  .check { display: flex; gap: 6px; align-items: center; font-size: 13px; }
  .roles { display: grid; gap: 6px; }
  .role { display: flex; gap: 8px; align-items: baseline; font-size: 13px; }
  .role span { display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline; }
  .preview ul { margin: 0; padding-left: 18px; display: grid; gap: 2px; font-size: 13px; }
  .count { font-size: 12px; color: var(--text-muted); background: var(--surface-2); border-radius: 999px; padding: 1px 7px; }
</style>
