<script lang="ts">
  // A live run's progress: trials done, spend so far, Stop. Shared by the run page and the claim page.
  import { app } from "../lib/app.svelte";
  import { num, usd } from "../lib/format";
  import type { RunProgress } from "../lib/progress";

  let { runId, progress }: { runId: string; progress: RunProgress } = $props();
</script>

<section class="card progress" aria-live="polite">
  <div class="bar"><span style:width={`${progress.total ? (progress.done / progress.total) * 100 : 0}%`}></span></div>
  <p><strong>{progress.done} / {progress.total}</strong> trials ·
    <span class="pass">{progress.passed} passed</span> · <span class="fail">{progress.failed} failed</span>
    {#if progress.errors} · <span class="fail">{progress.errors} errors</span>{/if}
    {#if progress.refused} · <span class="muted">{progress.refused} refused by the spend limit</span>{/if} · spent {usd(progress.spentUsd)}</p>
  {#if progress.budgetHit}<p class="note">Spend limit reached: paid calls that don't fit are refused.</p>{/if}
  {#each progress.warnings as warning}<p class="note">{warning}</p>{/each}
  {#each progress.running as r (r)}<p class="muted">running: {r}</p>{/each}
  <button onclick={() => app.backend?.cancel(runId)}>Stop after running trials</button>
  <div class="recent">
    {#each progress.recent as t (t.trial_id)}
      <div><span class={t.passed ? "pass" : "fail"}>{t.passed ? "✓" : t.status === "ok" ? "✗" : "!"}</span>
        {t.scenario} · {t.config} · {t.task_id} <span class="muted">{num(t.duration_s, 1)}s</span></div>
    {/each}
  </div>
</section>

<style>
  .progress { margin-top: 12px; }
  .bar { height: 8px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }
  .bar span { display: block; height: 100%; background: var(--accent); transition: width 0.3s; }
  .recent { margin-top: 12px; font-size: 13px; max-height: 240px; overflow: auto; }
</style>
