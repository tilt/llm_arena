<script lang="ts">
  import ClaimBand from "../components/ClaimBand.svelte";
  import RenameForm from "../components/RenameForm.svelte";
  import RunProgress from "../components/RunProgress.svelte";
  import ReportView from "../components/ReportView.svelte";
  import StepInspector from "../components/StepInspector.svelte";
  import type { Persistence } from "../lib/backend";
  import { app } from "../lib/app.svelte";
  import type { RunBundle } from "../lib/contracts";
  import { initialProgress, reduce, stopReason, type RunProgress as Progress } from "../lib/progress";
  import { refreshRuns } from "../lib/runs.svelte";

  let { id, trial, step }: { id: string; trial?: string; step?: string } = $props();
  let persistence = $state<Persistence>("server");

  let progress = $state<Progress>({ ...initialProgress });
  let live = $state(false);
  let bundle = $state<RunBundle | null>(null);
  let error = $state("");
  let renaming = $state(false);

  async function loadBundle() {
    try {
      bundle = await app.backend!.bundle(id);
      persistence = await app.backend!.persistence(id);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  $effect(() => {
    const backend = app.backend;
    if (!backend) return;
    progress = { ...initialProgress };
    bundle = null;
    error = "";
    live = false;
    let unsubscribe: (() => void) | null = null;
    backend.runs().then((runs) => {
      const listing = runs.find((r) => r.run_id === id);
      if (listing?.active) {
        live = true;
        unsubscribe = backend.events(id, (event) => {
          progress = reduce(progress, event);
          if (event.type === "run_finished") void loadBundle();
        });
      } else {
        void loadBundle();
      }
    });
    return () => unsubscribe?.();
  });

  const reportUrl = $derived(app.backend?.reportUrl(id) ?? null);
  const exportUrl = $derived(app.backend?.exportUrl(id) ?? null);
  const title = $derived(String(bundle?.run.name ?? "") || id);
  async function renamed(saved: boolean) {
    renaming = false;
    if (!saved) return;
    await loadBundle();
    void refreshRuns();
  }
</script>

<div class="head">
  <h1>{title}</h1>
  {#if bundle && !(live && !progress.finished) && !renaming}<button onclick={() => (renaming = true)}>Rename</button>{/if}
</div>
{#if title !== id}<p class="muted small id">Run <code>{id}</code></p>{/if}
{#if renaming && bundle}<RenameForm runId={id} {bundle} onclose={renamed} />{/if}
{#if live && !progress.finished}
  <RunProgress runId={id} {progress} />
{/if}
{#if stopReason(progress)}<p class="note">{stopReason(progress)}</p>{/if}
{#if error}<p class="note">{error}</p>{/if}
{#if bundle}
  {@const execution = (() => { try { return JSON.parse(String(bundle.run.execution_json || "{}")); } catch { return {}; } })()}
  {#if execution.backend}<p class="muted">Model code ran in: <strong>{execution.backend}</strong> ({execution.isolation || "unknown"}){execution.daemon ? `, ${execution.daemon} daemon` : ""}.</p>{/if}
  <p class="muted">
    {#if reportUrl}Standalone report: <a href={reportUrl} target="_blank" rel="noopener">open HTML report</a> · {/if}
    <a href={exportUrl ?? URL.createObjectURL(new Blob([JSON.stringify(bundle)], { type: "application/json" }))} download={`${id}.json`}>Download run bundle</a>
    <span class="muted">(traces and step files included)</span>
  </p>
  {#if persistence === "session"}
    <p class="note" role="status">This run is kept only for this browser session: the browser did not allow saving it (private window or
      storage full). Download the run bundle to keep its traces and files; you can import it later.</p>
  {/if}
  <ClaimBand runId={id} {bundle} />
  <ReportView {bundle} manifests={app.scenarios} runId={id} />
  {#if trial}<StepInspector runId={id} trialId={trial} {step} {bundle} />{/if}
{:else if !live && !error}
  <p class="muted">Loading…</p>
{/if}

<style>
  .head { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  .head h1 { margin-bottom: 0; overflow-wrap: anywhere; }
  .id { margin: 4px 0 12px; font-size: 12px; }
</style>
