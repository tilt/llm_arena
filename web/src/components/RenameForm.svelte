<script lang="ts">
  import { app } from "../lib/app.svelte";
  import type { RunBundle } from "../lib/contracts";
  import { nameFromSetup } from "../lib/setups";

  // Rename a finished run and its setups. Only names change: ids, links, results and the leaderboard ranking stay
  // (the leaderboard lists a setup under its name in the latest run).
  let { runId, bundle, onclose }: { runId: string; bundle: RunBundle; onclose: (saved: boolean) => void } = $props();

  const configs = $derived.by(() => {
    const listed = (JSON.parse(String(bundle.run.config_json ?? "{}")).configs ?? []) as { name?: string }[];
    const names = [...new Set([...listed.map((c) => c.name ?? ""), ...bundle.trials.map((t) => String(t.config))].filter(Boolean))];
    return names.map((name) => {
      const trial = bundle.trials.find((t) => t.config === name && t.setup_json);
      return { name, suggestion: trial ? nameFromSetup(JSON.parse(String(trial.setup_json))) : "" };
    });
  });
  let runName = $state("");
  let names = $state<Record<string, string>>({});
  let busy = $state(false);
  let error = $state("");
  $effect.pre(() => {
    runName = String(bundle.run.name ?? "");
    names = Object.fromEntries(configs.map((c) => [c.name, c.name]));
  });

  const trimmed = $derived(Object.entries(names).map(([old, name]) => [old, name.trim()] as const));
  const duplicate = $derived(new Set(trimmed.map(([, n]) => n)).size !== trimmed.length);
  const changed = $derived(runName.trim() !== String(bundle.run.name ?? "") || trimmed.some(([old, n]) => old !== n));
  const invalid = $derived(!runName.trim() || trimmed.some(([, n]) => !n) || duplicate);

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!app.backend || invalid) return;
    busy = true; error = "";
    try {
      await app.backend.renameRun(runId, {
        name: runName.trim(),
        configs: Object.fromEntries(trimmed.filter(([old, n]) => old !== n)),
      });
      onclose(true);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }
</script>

<form class="card rename" onsubmit={save} aria-labelledby="rename-title">
  <h2 id="rename-title">Rename this run</h2>
  <p class="muted small">Only names change: results, links and leaderboard rankings stay. The leaderboard lists a setup under
    its name in the latest run that used it.</p>
  <label>Run name <input type="text" bind:value={runName} required /></label>
  {#each configs as c (c.name)}
    <div class="setup">
      <label for={`rename-${c.name}`}>Setup {#if configs.length > 1}<code>{c.name}</code>{/if}</label>
      <input id={`rename-${c.name}`} type="text" bind:value={names[c.name]} required />
      {#if c.suggestion && names[c.name]?.trim() !== c.suggestion}
        <button type="button" class="link" onclick={() => (names[c.name] = c.suggestion)}
          title="Name it after the models it actually ran on">Use “{c.suggestion}”</button>
      {/if}
    </div>
  {/each}
  {#if duplicate}<p class="error" role="alert">Setup names must be different from each other.</p>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  <div class="actions">
    <button type="submit" class="primary" disabled={busy || invalid || !changed}>{busy ? "Saving…" : "Save names"}</button>
    <button type="button" onclick={() => onclose(false)}>Cancel</button>
  </div>
</form>

<style>
  .rename { display: grid; gap: 10px; margin: 0 0 16px; max-width: 640px; }
  h2 { margin: 0; font-size: 16px; }
  p { margin: 0; }
  label { display: grid; gap: 4px; font-size: 13px; }
  .setup { display: grid; gap: 4px; font-size: 13px; }
  .small { font-size: 12px; }
  .error { color: var(--critical); font-size: 13px; }
  .actions { display: flex; gap: 8px; }
  .link { background: none; border: none; color: var(--accent); padding: 0; text-decoration: underline; cursor: pointer; font-size: 13px; justify-self: start; }
</style>
