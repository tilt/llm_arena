<script lang="ts">
  import { app } from "../lib/app.svelte";
  import type { TrialTrace } from "../lib/backend";
  import { llmRoles, policyLabel } from "../lib/builder";
  import type { DecisionConfig, RunBundle, Span, TaskView } from "../lib/contracts";
  import { num, usd } from "../lib/format";
  import { executions, stepStats, trialWorkflow, whyNotRun } from "../lib/inspect";
  import { go } from "../lib/router.svelte";
  import { scenarioTasks } from "../lib/tasks";
  import ArtifactView from "./ArtifactView.svelte";
  import ExpectationView from "./ExpectationView.svelte";
  import SpanView from "./SpanView.svelte";
  import WorkflowDiagram from "./WorkflowDiagram.svelte";

  // A trial's run, step by step: the workflow as a map (how often each step ran) and every execution of the
  // selected step with its input, output and files. The URL holds trial and step, so views are deep-linkable.
  let { runId, trialId, step = "", bundle }: { runId: string; trialId: string; step?: string; bundle: RunBundle } = $props();

  let trace = $state<TrialTrace | null>(null);
  let loading = $state(true);
  let error = $state("");
  let taskView = $state<TaskView | null>(null);
  let taskLoading = $state(false);
  let taskError = $state("");
  let dialog = $state<HTMLElement | null>(null);
  let returnFocus: Element | null = null;

  const trial = $derived(bundle.trials.find((t) => String(t.trial_id) === trialId) ?? null);
  const manifest = $derived(app.scenarios.find((s) => s.id === trial?.scenario));
  const flow = $derived(manifest && trial ? trialWorkflow(manifest, trial) : null);
  const spans = $derived((trace?.spans ?? []) as Span[]);
  const stats = $derived(stepStats(spans));
  const order = $derived((flow?.steps ?? []).map((s) => s.id).filter((id) => id !== "start"));
  // The start step shows the task the trial was given: a walk through the trial begins there (arrow keys go on).
  const hasTask = $derived(flow?.steps.some((s) => s.id === "start") ?? false);
  const current = $derived(step || (hasTask ? "start" : order.find((id) => (stats[id]?.runs ?? 0) > 0)) || "");
  const currentStep = $derived(flow?.steps.find((s) => s.id === current));
  const taskSelected = $derived(current === "start");
  const keyOrder = $derived(hasTask ? ["start", ...order] : order);
  // Tasks load from the scenario as it is now; a trial recorded on another version may have seen a different one.
  const ranVersion = $derived(String(trial?.scenario_version ?? ""));
  const versionNote = $derived(!manifest?.version || ranVersion === manifest.version ? ""
    : ranVersion ? `This trial ran on version ${ranVersion} of the scenario; the task below is from the current version (${manifest.version}) and may differ.`
    : `This trial does not record its scenario version; the task below is from the current version (${manifest.version}).`);
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
  // Why a failed trial failed: the pass criteria that failed (with the evaluators' reasons), other telling signals,
  // and the step where it last went wrong.
  const SIGNALS: Record<string, string> = {
    regressed: "A revision broke a result that was already correct.",
    critic_fp: "The critic asked for changes although the draft was already correct.",
    critic_fn: "The critic accepted a draft that was wrong.",
  };
  const diagnosis = $derived.by(() => {
    if (!trial || trial.passed) return null;
    const criteria = new Set(manifest?.pass_criteria ?? []);
    const failed = scores.filter((s) => criteria.has(String(s.name)) && s.passed === false)
      .map((s) => ({ name: String(s.name), why: String(s.rationale ?? "") }));
    const signals = scores.filter((s) => SIGNALS[String(s.name)] && Number(s.value) > 0).map((s) => SIGNALS[String(s.name)]!);
    let where: { step: string; label: string; run: number; error: string } | null = null;
    for (let i = spans.length - 1; i >= 0 && !where; i--) {
      const s = spans[i]!;
      if (s.step && s.step !== "end" && (s.error || s.attrs?.ok === false)) {
        const list = executions(spans, s.step);
        const run = list.findIndex((e) => e.index === i || e.children.some((c) => c.index === i)) + 1;
        const text = s.error ?? (typeof s.output === "string" ? s.output : "");
        const last = text.trim().split("\n").filter(Boolean).at(-1) ?? "";
        where = { step: s.step, label: flow?.steps.find((f) => f.id === s.step)?.label ?? s.step, run, error: last };
      }
    }
    if (!failed.length && !signals.length && !where && !trial.error) return null;
    return { failed, signals, where };
  });
  // When the result has no image (e.g. the final code crashed), show the last one a step produced.
  const lastImage = $derived.by(() => {
    for (let i = spans.length - 1; i >= 0; i--) {
      const s = spans[i]!;
      const image = s.kind !== "llm_call" && s.step !== "end" ? (s.artifacts ?? []).find((a) => a.media_type.startsWith("image/") && a.key) : undefined;
      if (image && s.step) {
        const run = executions(spans, s.step).findIndex((e) => e.index === i || e.children.some((c) => c.index === i)) + 1;
        return { artifact: image, step: s.step, label: flow?.steps.find((f) => f.id === s.step)?.label ?? s.step, run };
      }
    }
    return null;
  });
  const resultHasImage = $derived(spans.some((s) => s.step === "end" && (s.artifacts ?? []).some((a) => a.media_type.startsWith("image/"))));
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
    const backend = app.backend;
    const scenario = manifest?.id;
    const taskId = String(trial?.task_id ?? "");
    if (!taskSelected) {
      taskView = null;
      taskLoading = false;
      taskError = "";
      return;
    }
    if (!backend || !scenario || !taskId) return;
    let stale = false;
    taskLoading = true;
    taskError = "";
    taskView = null;
    scenarioTasks(backend, scenario).then(
      (tasks) => {
        if (stale) return;
        taskView = tasks.find((t) => t.id === taskId) ?? null;
        taskLoading = false;
      },
      (e) => {
        if (stale) return;
        taskError = e instanceof Error ? e.message : String(e);
        taskLoading = false;
      },
    );
    return () => { stale = true; };
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
    if (!typing && (event.key === "ArrowDown" || event.key === "ArrowUp") && keyOrder.length) {
      event.preventDefault();
      const at = Math.max(0, keyOrder.indexOf(current));
      select(keyOrder[Math.min(keyOrder.length - 1, Math.max(0, at + (event.key === "ArrowDown" ? 1 : -1)))]!);
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
        {#if diagnosis}
          <section class="diagnosis" aria-labelledby="why-title">
            <h3 id="why-title">Why this trial failed</h3>
            {#if trial?.error}<p>The trial stopped with an error: <code>{String(trial.error).split("\n")[0]}</code></p>{/if}
            {#if diagnosis.failed.length}
              <ul>{#each diagnosis.failed as f (f.name)}<li><strong>{f.name}</strong>{#if f.why}: {f.why}{/if}</li>{/each}</ul>
            {/if}
            {#each diagnosis.signals as s (s)}<p class="signal">{s}</p>{/each}
            {#if diagnosis.where}
              <p>Last error in <strong>{diagnosis.where.label}</strong>{diagnosis.where.run > 1 ? ` (run ${diagnosis.where.run})` : ""}{#if diagnosis.where.error}: <code>{diagnosis.where.error}</code>{/if}
                {#if current !== diagnosis.where.step}<button class="link" onclick={() => select(diagnosis!.where!.step)}>Go to this step</button>{/if}</p>
            {/if}
          </section>
        {/if}
        <h3>{currentStep.label}{#if currentStep.role} <span class="pill">{currentStep.role}: {roles[currentStep.role] ?? "—"}</span>{/if}</h3>
        {#if currentStep.description}<p class="muted">{currentStep.description}</p>{/if}
        {#if taskSelected}
          <article class="task card" aria-busy={taskLoading}>
            {#if !manifest}
              <p class="muted">This scenario is not available here, so its task cannot be shown.</p>
            {:else if taskLoading}
              <div class="skeleton short" aria-label="Loading the task"></div>
            {:else if taskError}
              <p class="error" role="alert">The task could not be loaded: {taskError}</p>
            {:else if !taskView}
              <p class="muted">Task <code>{trial?.task_id}</code> is not in the current version of {manifest.title}, so its prompt
                cannot be shown.</p>
            {:else}
              {#if versionNote}<p class="note">{versionNote}</p>{/if}
              <div>
                <h4>Prompt</h4>
                <p class="prompt">{taskView.prompt}</p>
                {#if taskView.note}<p class="note">{taskView.note}</p>{/if}
              </div>
              {#if taskView.expected?.length}
                <div class="expected">
                  <h4>Counts as correct</h4>
                  {#each taskView.expected as expectation, i (i)}<ExpectationView {expectation} />{/each}
                </div>
              {/if}
            {/if}
          </article>
        {:else if !runs.length}
          <p class="muted">{flow ? whyNotRun(flow, spans, current) : "This step did not run in this trial."}</p>
        {/if}
        {#if current === "end" && !resultHasImage && lastImage}
          <article class="card no-result">
            <p><strong>No final {lastImage.artifact.name.replace(/\.[a-z]+$/, "")}.</strong> The last one that rendered came from
              <button class="link" onclick={() => select(lastImage!.step)}>{lastImage.label}{lastImage.run > 1 ? `, run ${lastImage.run}` : ""}</button>:</p>
            <ArtifactView {runId} artifact={lastImage.artifact} />
          </article>
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
  header > div { min-width: 0; }
  h2 { margin: 0; font-size: 18px; overflow-wrap: anywhere; }
  h2:focus { outline: none; }
  .meta { margin: 2px 0 0; font-size: 13px; }
  .close { align-self: start; white-space: nowrap; }
  kbd { font-size: 11px; border: 1px solid var(--border); border-radius: 4px; padding: 0 4px; margin-left: 4px; color: var(--text-muted); }
  .scores { padding: 6px 18px; border-bottom: 1px solid var(--border); font-size: 13px; }
  .scores summary { cursor: pointer; }
  .body { flex: 1; display: grid; grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.4fr); min-height: 0; }
  .map { overflow: auto; padding: 14px; border-right: 1px solid var(--border); }
  .detail { overflow: auto; padding: 14px 18px; display: grid; gap: 12px; align-content: start; }
  h3 { margin: 0; font-size: 16px; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .execution { display: grid; gap: 8px; }
  .task { display: grid; gap: 14px; }
  .task h4 { margin: 0 0 6px; font-size: 13px; }
  .prompt { margin: 0; white-space: pre-wrap; }
  .expected { display: grid; gap: 10px; align-content: start; }
  .diagnosis { border: 1px solid color-mix(in srgb, var(--critical) 55%, var(--border)); background: color-mix(in srgb, var(--critical) 7%, var(--surface-1));
    border-radius: var(--radius); padding: 12px 14px; display: grid; gap: 6px; }
  .diagnosis h3 { font-size: 15px; }
  .diagnosis ul { margin: 0; padding-left: 18px; }
  .diagnosis p { margin: 0; }
  .diagnosis code { font-size: 12px; overflow-wrap: anywhere; }
  .signal::before { content: "⚠ "; color: var(--critical); }
  .no-result { display: grid; gap: 8px; }
  .no-result p { margin: 0; }
  .count { margin: 0; font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .skeleton { height: 140px; border-radius: 10px; background: linear-gradient(90deg, var(--surface-1), var(--surface-2), var(--surface-1)); background-size: 200% 100%; animation: shimmer 1.2s infinite; }
  .skeleton.short { height: 60px; }
  @keyframes shimmer { to { background-position: -200% 0; } }
  @media (prefers-reduced-motion: reduce) { .skeleton { animation: none; } }
  @media (max-width: 860px) {
    .inspector { inset: 0; border-radius: 0; }
    .body { grid-template-columns: minmax(0, 1fr); overflow: auto; }
    header { flex-wrap: wrap; }
    .map { border-right: none; border-bottom: 1px solid var(--border); overflow-x: auto; overflow-y: visible; }
    .detail { overflow: visible; }
  }
</style>
