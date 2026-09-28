<script lang="ts">
  import ModelRefInput from "../components/ModelRefInput.svelte";
  import { app } from "../lib/app.svelte";
  import { KINDS, activeBaseline, setActiveBaseline } from "../lib/baselines";
  import type { BaselineProfile } from "../lib/contracts";

  // Baseline profiles: one model per kind of step. New setups start from the active profile; a replacement study
  // swaps one step at a time against it.
  const SHIPPED = new Set(["local-small", "openai-mini"]);
  let drafts = $state<Record<string, BaselineProfile>>({});
  let active = $state(activeBaseline());
  let saving = $state("");
  let message = $state("");
  let newName = $state("");

  $effect(() => {
    drafts = structuredClone($state.snapshot(app.baselines)) as Record<string, BaselineProfile>;
  });

  const catalog = $derived(app.models?.models ?? []);
  const visionModels = $derived(catalog.filter((m) => Boolean((m.spec.capabilities as { vision?: boolean } | undefined)?.vision)));
  const ollaya = $derived(app.runtime?.decision_services?.ollaya);
  const jev = $derived(app.runtime?.decision_services?.jev);
  const serviceOptions = $derived([
    ...(ollaya?.models ?? []).map((m) => ({ value: `ollaya:${m}`, label: `Ollaya · ${m}` })),
    { value: "jev:jev-latest", label: "Jev (TypeSafe)" },
  ]);
  const changed = (name: string) => JSON.stringify(drafts[name]) !== JSON.stringify(app.baselines[name]);

  async function save(name: string) {
    if (!app.backend) return;
    saving = name; message = "";
    try {
      app.baselines = await app.backend.saveBaseline(name, $state.snapshot(drafts[name]!) as BaselineProfile);
      message = `Saved “${drafts[name]!.label}”${app.mode === "local" ? " (configs/baselines.local.yaml)" : " in this browser"}.`;
    } catch (e) { message = e instanceof Error ? e.message : String(e); }
    finally { saving = ""; }
  }
  async function reset(name: string) {
    if (!app.backend) return;
    app.baselines = await app.backend.saveBaseline(name, null);
    message = SHIPPED.has(name) ? "Restored the shipped profile." : "Profile removed.";
    if (active === name && !app.baselines[name]) choose("local-small");
  }
  function choose(name: string) {
    active = name;
    setActiveBaseline(name);
  }
  function addProfile() {
    const name = newName.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
    if (!name || drafts[name]) { message = name ? `A profile “${name}” exists already.` : "Give the profile a name."; return; }
    drafts[name] = { ...(structuredClone($state.snapshot(drafts[active] ?? drafts["local-small"]!)) as BaselineProfile), label: newName.trim(), description: "" };
    newName = "";
    message = `Added “${drafts[name]!.label}” as a copy of the active profile. Choose its models, then save.`;
  }
</script>

<h1>Baseline models</h1>
<p class="lead">
  A baseline gives every step of every scenario a model by the kind of work it does. Start from one to get comparable
  results quickly, then replace the model of a single step to see what that step's model is worth.
</p>

{#if message}<p class="note" role="status">{message}</p>{/if}

<div class="profiles">
  {#each Object.entries(drafts) as [name, profile] (name)}
    <section class="card profile" class:active={active === name} aria-labelledby={`p-${name}`}>
      <header>
        <div>
          <h2 id={`p-${name}`} class="sr-only">{profile.label}</h2>
          <input class="title" type="text" bind:value={profile.label} aria-label="Profile name" />
          <textarea rows="3" bind:value={profile.description} aria-label="Description" placeholder="What this profile is for"></textarea>
        </div>
        <label class="use"><input type="radio" name="active" checked={active === name} onchange={() => choose(name)} /> New setups start here</label>
      </header>
      <div class="kinds">
        {#each KINDS as k (k.kind)}
          <div class="kind">
            <label for={`${name}-${k.kind}`}><strong>{k.label}</strong> <span class="muted">{k.hint}</span></label>
            <ModelRefInput id={`${name}-${k.kind}`} bind:value={(profile.models as Record<string, string>)[k.kind]!}
              options={k.kind === "vision" ? visionModels : catalog} label={`${profile.label}, ${k.label}`} />
          </div>
        {/each}
        <div class="kind">
          <label for={`${name}-service`}><strong>Decision model</strong> <span class="muted">a dedicated model for control decisions (optional)</span></label>
          <select id={`${name}-service`} bind:value={profile.decision_service}>
            <option value={null}>none: decisions use the Decision model above</option>
            {#each serviceOptions as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
            {#if profile.decision_service && !serviceOptions.some((o) => o.value === profile.decision_service)}
              <option value={profile.decision_service}>{profile.decision_service} (not available right now)</option>
            {/if}
          </select>
          {#if profile.decision_service?.startsWith("jev") && jev?.status !== "available"}<p class="muted small">Jev: {jev?.status}</p>{/if}
        </div>
      </div>
      <footer>
        <button class="primary" onclick={() => save(name)} disabled={saving === name || !changed(name)}>Save</button>
        <button onclick={() => reset(name)}>{SHIPPED.has(name) ? "Restore shipped version" : "Delete"}</button>
        {#if changed(name)}<span class="muted small">Unsaved changes</span>{/if}
      </footer>
    </section>
  {/each}
</div>

<section class="card add">
  <label for="new-profile">New profile</label>
  <input id="new-profile" type="text" bind:value={newName} placeholder="e.g. Local medium" />
  <button onclick={addProfile}>Add a copy of the active profile</button>
</section>

<style>
  .profiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 16px; }
  @media (max-width: 520px) { .profiles { grid-template-columns: 1fr; } }
  .profile { display: grid; gap: 12px; }
  .profile.active { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
  header { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
  header > div { display: grid; gap: 6px; flex: 1; }
  .title { font-size: 17px; font-weight: 600; width: 100%; }
  textarea { width: 100%; resize: vertical; font: inherit; font-size: 13px; }
  .use { display: flex; gap: 6px; align-items: center; font-size: 13px; white-space: nowrap; }
  .kinds { display: grid; gap: 10px; }
  .kind { display: grid; gap: 4px; }
  .kind label { font-size: 13px; }
  .kind select { width: 100%; }
  footer { display: flex; gap: 8px; align-items: center; }
  .small { font-size: 12px; margin: 2px 0 0; }
  .add { display: flex; gap: 8px; align-items: center; margin-top: 16px; flex-wrap: wrap; }
</style>
