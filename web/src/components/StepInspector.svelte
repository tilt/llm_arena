<script lang="ts">
  import { app } from "../lib/app.svelte";
  import type { TrialTrace } from "../lib/backend";
  import { llmRoles, policyLabel } from "../lib/builder";
  import type { DecisionConfig, RunBundle, Span } from "../lib/contracts";
  import { num, usd } from "../lib/format";
  import { executions, stepStats, trialWorkflow } from "../lib/inspect";
  import { go } from "../lib/router.svelte";
  import SpanView from "./SpanView.svelte";
  import WorkflowDiagram from "./WorkflowDiagram.svelte";

  // A trial's run, step by step: the workflow as a map (how often each step ran) and every execution of the
  // selected step with its input, output and files. The URL holds trial and step, so views are deep-linkable.
  let { runId, trialId, step = "", bundle }: { runId: string; trialId: string; step?: string; bundle: RunBundle } = $props();

  let trace = $state<TrialTrace | null>(null);
  let loading = $state(true);
  let error = $state("");
  let dialog = $state<HTMLElement | null>(null);
  let returnFocus: Element | null = null;

  const trial = $derived(bundle.trials.find((t) => String(t.trial_id) === trialId) ?? null);
  const manifest = $derived(app.scenarios.find((s) => s.id === trial?.scenario));
  const flow = $derived(manifest && trial ? trialWorkflow(manifest, trial) : null);
  const spans = $derived((trace?.spans ?? []) as Span[]);
  const stats = $derived(stepStats(spans));
  const order = $derived((flow?.steps ?? []).map((s) => s.id).filter((id) => id !== "start"));
  const current = $derived(step || order.find((id) => (stats[id]?.runs ?? 0) > 0) || "");
  const currentStep = $derived(flow?.steps.find((s) => s.id === current));
  const runs = $derived(current ? executions(spans, current) : []);
  // Decision roles show the policy that actually decided (rules, ollaya winnow:e4b, …) unless it called an LLM role.
  const decisions = $derived((parse(trial?.setup_json).decisions ?? null) as unknown as DecisionConfig | null);
  const roles = $derived.by(() => {
    const bound: Record<string, string> = { ...parse(trial?.roles_json) };
    for (const role of ["decider", "escalation"]) {
      if (decisions && !llmRoles(decisions).includes(role)) bound[role] = policyLabel(decisions);
    }
    return bound;
  });
  const scores = $derived(bundle.scores.filter((s) => s.trial_id === trialId));
  const untagged = $derived(spans.filter((s) => !s.step && ["llm_call", "tool_call", "code_exec"].includes(s.kind)).length);

  function parse(value: unknown): Record<string, string> & { decisions?: unknown } {
    try { return typeof value === "string" ? JSON.parse(value) : {}; } catch { return {}; }
  }
  const outputOf = (s: Span) => (typeof s.output === "string" ? s.output : "");

  $effect(() => {
    loading = true; error = ""; trace = null;
    app.backend?.trace(runId, trialId).then(
      (found) => { trace = found; loading = false; if (!found) error = "No trace was stored for this trial."; },
      (e) => { error = e instanceof Error ? e.message : String(e); loading = false; },
    );
  });

  $effect(() => {
    // Modal: the page behind must not scroll, and focus returns where it was when the inspector closes.
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    returnFocus = document.activeElement;
    dialog?.querySelector<HTMLElement>("h2")?.focus();
    return () => {
      document.body.style.overflow = overflow;
      (returnFocus as HTMLElement | null)?.focus?.();
    };
  });

  const select = (id: string) => go(`/runs/${encodeURIComponent(runId)}/trial/${encodeURIComponent(trialId)}/step/${encodeURIComponent(id)}`);
  const close = () => go(`/runs/${encodeURIComponent(runId)}`);

  function onkeydown(event: KeyboardEvent) {
    const typing = (event.target as HTMLElement).closest("input, select, textarea");
    if (event.key === "Escape") { event.preventDefault(); close(); return; }
    if (!typing && (event.key === "ArrowDown" || event.key === "ArrowUp") && order.length) {
      event.preventDefault();
      const at = Math.max(0, order.indexOf(current));
      select(order[Math.min(order.length - 1, Math.max(0, at + (event.key === "ArrowDown" ? 1 : -1)))]!);
    }
    if (event.key === "Tab" && dialog) {
      // Keep focus inside the dialog.
      const focusable = [...dialog.querySelectorAll<HTMLElement>("a[href], button, [tabindex='0'], select, input, summary")].filter((el) => !el.hasAttribute("disabled"));
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }
</script>

<div class="backdrop" role="presentation" onclick={close}></div>
<div class="inspector" role="dialog" aria-modal="true" aria-labelledby="inspector-title" tabindex="-1" bind:this={dialog} {onkeydown}>
  <header>
    <div>
      <h2 id="inspector-title" tabindex="-1">
        <span class={trial?.passed ? "pass" : "fail"}>{trial?.passed ? "✓ passed" : "✗ failed"}</span>
        {manifest?.title ?? trial?.scenario} · {trial?.task_id}
      </h2>
      <p class="muted meta">{trial?.config}{trial?.repeat ? ` · repeat ${trial.repeat}` : ""} · {num(Number(trial?.duration_s ?? 0), 1)} s ·
        {(Number(trial?.prompt_tokens ?? 0) + Number(trial?.completion_tokens ?? 0)).toLocaleString("en-US")} tokens · {usd(Number(trial?.cost_usd ?? 0))}</p>
    </div>
    <button class="close" onclick={close} aria-label="Close the step inspector">Close <kbd>Esc</kbd></button>
  </header>

  {#if trial?.error}<p class="note" role="alert">{String(trial.error).split("\n")[0]}</p>{/if}
  <details class="scores">
    <summary>Scores ({scores.filter((s) => s.passed === true).length} passed, {scores.filter((s) => s.passed === false).length} failed)</summary>
    <div class="table-wrap"><table>
      <thead><tr><th>Score</th><th>Level</th><th class="n">Value</th><th>Why</th></tr></thead>
      <tbody>{#each scores as s (String(s.name))}<tr><td>{s.name}</td><td>{s.level}</td>
        <td class="n" class:pass={s.passed === true} class:fail={s.passed === false}>{num(Number(s.value))}{s.passed === true ? " ✓" : s.passed === false ? " ✗" : ""}</td>
        <td>{s.rationale}</td></tr>{/each}</tbody>
    </table></div>
  </details>

  <div class="body">
    <aside class="map" aria-label="Workflow of this trial">
      {#if flow}
        <WorkflowDiagram {flow} models={roles} {stats} selected={current} onselect={select} label="Workflow of this trial; select a step" />
        <p class="muted small">Numbers show how often a step ran; faded steps did not run. ↑ ↓ move between steps.</p>
      {/if}
    </aside>
    <section class="detail" aria-live="polite">
      {#if loading}
        <div class="skeleton" aria-busy="true"></div><div class="skeleton short"></div>
      {:else if error}
        <p class="note">{error}</p>
      {:else if currentStep}
        <h3>{currentStep.label}{#if currentStep.role} <span class="pill">{currentStep.role}: {roles[currentStep.role] ?? "—"}</span>{/if}</h3>
        {#if currentStep.description}<p class="muted">{currentStep.description}</p>{/if}
        {#if !runs.length}
          <p class="muted">This step did not run in this trial.</p>
        {/if}
        {#each runs as execution, i (execution.index)}
          <article class="execution card">
            {#if runs.length > 1}<p class="count">Run {i + 1} of {runs.length}</p>{/if}
            <SpanView {runId} span={execution.span} previous={i > 0 ? outputOf(runs[i - 1]!.span) : ""} />
            {#each execution.children as child (child.index)}
              <SpanView {runId} span={child.span} nested />
            {/each}
          </article>
        {/each}
        {#if untagged}<p class="muted small">{untagged} calls of this trial are not linked to a step (recorded before step tracking existed).</p>{/if}
      {/if}
    </section>
  </div>
</div>

<style>
  .backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.45); z-index: 40; }
  .inspector { position: fixed; inset: 24px; z-index: 41; background: var(--page); border: 1px solid var(--border); border-radius: 14px;
    display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35); }
  .inspector:focus { outline: none; }
  header { display: flex; justify-content: space-between; gap: 12px; padding: 14px 18px; border-bottom: 1px solid var(--border); background: var(--surface-1); }
  h2 { margin: 0; font-size: 18px; }
  h2:focus { outline: none; }
  .meta { margin: 2px 0 0; font-size: 13px; }
  .close { align-self: start; white-space: nowrap; }
  kbd { font-size: 11px; border: 1px solid var(--border); border-radius: 4px; padding: 0 4px; margin-left: 4px; color: var(--text-muted); }
  .scores { padding: 6px 18px; border-bottom: 1px solid var(--border); font-size: 13px; }
  .scores summary { cursor: pointer; }
  .body { flex: 1; display: grid; grid-template-columns: minmax(300px, 0.9fr) minmax(360px, 1.4fr); min-height: 0; }
  .map { overflow: auto; padding: 14px; border-right: 1px solid var(--border); }
  .detail { overflow: auto; padding: 14px 18px; display: grid; gap: 12px; align-content: start; }
  h3 { margin: 0; font-size: 16px; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .execution { display: grid; gap: 8px; }
  .count { margin: 0; font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .small { font-size: 12px; }
  .skeleton { height: 140px; border-radius: 10px; background: linear-gradient(90deg, var(--surface-1), var(--surface-2), var(--surface-1)); background-size: 200% 100%; animation: shimmer 1.2s infinite; }
  .skeleton.short { height: 60px; }
  @keyframes shimmer { to { background-position: -200% 0; } }
  @media (prefers-reduced-motion: reduce) { .skeleton { animation: none; } }
  @media (max-width: 860px) {
    .inspector { inset: 0; border-radius: 0; }
    .body { grid-template-columns: 1fr; overflow: auto; }
    .map { border-right: none; border-bottom: 1px solid var(--border); overflow: visible; }
    .detail { overflow: visible; }
  }
</style>
