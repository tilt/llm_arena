<script lang="ts">
  import ReportView from "../components/ReportView.svelte";
  import StepInspector from "../components/StepInspector.svelte";
  import type { Persistence } from "../lib/backend";
  import { app } from "../lib/app.svelte";
  import type { RunBundle } from "../lib/contracts";
  import { num, usd } from "../lib/format";
  import { initialProgress, reduce, type RunProgress } from "../lib/progress";

  let { id, trial, step }: { id: string; trial?: string; step?: string } = $props();
  let persistence = $state<Persistence>("server");

  let progress = $state<RunProgress>({ ...initialProgress });
  let live = $state(false);
  let bundle = $state<RunBundle | null>(null);
  let error = $state("");

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
</script>

<h1>{id}</h1>
{#if live && !progress.finished}
  <section class="card progress" aria-live="polite">
    <div class="bar"><span style:width={`${progress.total ? (progress.done / progress.total) * 100 : 0}%`}></span></div>
    <p><strong>{progress.done} / {progress.total}</strong> trials ·
      <span class="pass">{progress.passed} passed</span> · <span class="fail">{progress.failed} failed</span>
      {#if progress.errors} · <span class="fail">{progress.errors} errors</span>{/if} · spent {usd(progress.spentUsd)}</p>
    {#if progress.budgetHit}<p class="note">Spend limit reached: no new trials start.</p>{/if}
    {#each progress.running as r (r)}<p class="muted">running: {r}</p>{/each}
    <button onclick={() => app.backend?.cancel(id)}>Stop after running trials</button>
    <div class="recent">
      {#each progress.recent as t (t.trial_id)}
        <div><span class={t.passed ? "pass" : "fail"}>{t.passed ? "✓" : t.status === "ok" ? "✗" : "!"}</span>
          {t.scenario} · {t.config} · {t.task_id} <span class="muted">{num(t.duration_s, 1)}s</span></div>
      {/each}
    </div>
  </section>
{/if}
{#if progress.finished && progress.stoppedEarly}<p class="note">The run stopped early (cancelled or spend limit).</p>{/if}
{#if error}<p class="note">{error}</p>{/if}
{#if bundle}
  <p class="muted">
    {#if reportUrl}Standalone report: <a href={reportUrl} target="_blank" rel="noopener">open HTML report</a> · {/if}
    <a href={exportUrl ?? URL.createObjectURL(new Blob([JSON.stringify(bundle)], { type: "application/json" }))} download={`${id}.json`}>Download run bundle</a>
    <span class="muted">(traces and step files included)</span>
  </p>
  {#if persistence === "session"}
    <p class="note" role="status">This run is kept only for this browser session: the browser did not allow saving it (private window or
      storage full). Download the run bundle to keep its traces and files; you can import it later.</p>
  {/if}
  <ReportView {bundle} manifests={app.scenarios} runId={id} />
  {#if trial}<StepInspector runId={id} trialId={trial} {step} {bundle} />{/if}
{:else if !live && !error}
  <p class="muted">Loading…</p>
{/if}

<style>
  .progress { margin-top: 12px; }
  .bar { height: 8px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
  .bar span { display: block; height: 100%; background: var(--accent); transition: width 0.3s; }
  .recent { margin-top: 12px; font-size: 13px; max-height: 240px; overflow: auto; }
</style>
