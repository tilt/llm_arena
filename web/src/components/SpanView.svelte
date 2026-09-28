<script lang="ts">
  import type { Span } from "../lib/contracts";
  import { num, pct, usd } from "../lib/format";
  import { conversation, images, lineDiff, text } from "../lib/inspect";
  import ArtifactView from "./ArtifactView.svelte";
  import CodeBlock from "./CodeBlock.svelte";
  import SpanView from "./SpanView.svelte";

  // One span, rendered by kind. `previous`: the previous execution's output, for "what changed" on revisions.
  let { runId, span, previous = "", nested = false }: { runId: string; span: Span; previous?: string; nested?: boolean } = $props();

  let fullConversation = $state(false);
  let showDiff = $state(false);
  const attrs = $derived((span.attrs ?? {}) as Record<string, unknown>);
  const view = $derived(span.kind === "llm_call" ? conversation(span.input) : null);
  const imageKeys = $derived(new Set((view?.all ?? []).flatMap((m) => images(m.content))));
  const shownImages = $derived((span.artifacts ?? []).filter((a) => imageKeys.has(a.key ?? "")));
  const otherArtifacts = $derived((span.artifacts ?? []).filter((a) => !imageKeys.has(a.key ?? "")));
  const output = $derived(typeof span.output === "string" ? span.output : span.output == null ? "" : JSON.stringify(span.output, null, 2));
  const diff = $derived(showDiff && previous ? lineDiff(previous, output) : []);
  const KIND: Record<string, string> = {
    llm_call: "Model call", tool_call: "Tool call", code_exec: "Code execution", decision: "Control decision",
    critique: "Critique", plan: "Plan", handoff: "Handoff", step: "Step", judge: "Judge",
  };
  const pretty = (value: unknown) => (typeof value === "string" ? value : JSON.stringify(value, null, 2));

  type Answer = { type?: string; probabilities?: Record<string, number>; choice?: string | null; confidence?: number;
    abstained?: boolean; escalated?: boolean; source?: string };
  const answers = $derived(span.kind === "decision" ? (span.output ?? {}) as Record<string, Answer> : {});
  const labels = $derived((attrs.labels ?? {}) as Record<string, unknown>);
  function predicted(a: Answer): string {
    if (a.abstained) return "no opinion";
    if (a.type === "noul") return (a.probabilities?.true ?? 0) >= 0.5 ? "yes" : "no";
    return a.choice ?? "—";
  }
  const truth = (value: unknown) => (typeof value === "boolean" ? (value ? "yes" : "no") : value == null ? "" : String(value));
</script>

<section class="span" class:nested class:error={!!span.error || attrs.ok === false}>
  <header>
    <span class="kind">{KIND[span.kind] ?? span.kind}</span>
    <strong>{span.name}</strong>
    {#if span.model}<span class="pill">{span.model}</span>{/if}
    <span class="facts">
      {num(span.duration_s ?? 0, 2)} s
      {#if span.kind === "llm_call"} · {(span.prompt_tokens ?? 0).toLocaleString("en-US")} in / {(span.completion_tokens ?? 0).toLocaleString("en-US")} out tokens{/if}
      {#if span.cost_usd} · {usd(span.cost_usd)}{/if}
    </span>
  </header>
  {#if span.error}<p class="fail" role="alert">Error: {span.error}</p>{/if}

  {#if span.kind === "llm_call" && view}
    {#if view.system}
      <details><summary>System prompt</summary><CodeBlock text={view.system} label="system" /></details>
    {/if}
    <h4>Input {#if view.earlier}<span class="muted">· new since the model's last turn ({view.earlier} earlier messages)</span>{/if}</h4>
    {#each fullConversation ? view.all.filter((m) => m.role !== "system") : view.latest as message, i (i)}
      <CodeBlock text={text(message.content) || pretty(message.tool_calls ?? "")} label={message.role ?? "message"} />
    {/each}
    {#if view.earlier}
      <button class="link" onclick={() => (fullConversation = !fullConversation)} aria-expanded={fullConversation}>
        {fullConversation ? "Show only the new messages" : `Show the full conversation (${view.all.length} messages)`}</button>
    {/if}
    {#each shownImages as artifact (artifact.key)}<ArtifactView {runId} {artifact} />{/each}
    <h4>Output</h4>
    <CodeBlock text={output} label="model reply" />
    {#if Array.isArray(attrs.tool_calls) && attrs.tool_calls.length}
      <CodeBlock text={pretty(attrs.tool_calls)} label="tool calls" language="json" />
    {/if}
    {#if attrs.reasoning_chars}<p class="muted small">Reasoning (hidden thinking): {Number(attrs.reasoning_chars).toLocaleString("en-US")} characters.</p>{/if}
  {:else if span.kind === "tool_call"}
    <h4>Input</h4><CodeBlock text={pretty(span.input)} label="arguments" language="json" />
    <h4>Output {#if attrs.error_kind}<span class="pill fail-pill">{String(attrs.error_kind)}</span>{/if}</h4>
    <CodeBlock text={output} label="result" />
  {:else if span.kind === "code_exec"}
    <h4>Input</h4><CodeBlock text={String(span.input ?? "")} label="code" language="python" />
    <h4>Output {#if attrs.ok === false}<span class="pill fail-pill">failed</span>{/if}</h4>
    <CodeBlock text={output} label="stdout / stderr" />
  {:else if span.kind === "decision"}
    <div class="table-wrap">
      <table>
        <thead><tr><th>Question</th><th>Answer</th><th class="n">Confidence</th><th>Probabilities</th><th>Ground truth</th></tr></thead>
        <tbody>
          {#each Object.entries(answers) as [question, a] (question)}
            {@const label = truth(labels[question])}
            <tr>
              <td>{question}</td>
              <td><strong>{predicted(a)}</strong>{#if a.escalated} <span class="pill">escalated</span>{/if}<div class="muted small">{a.source}</div></td>
              <td class="n">{a.abstained ? "–" : pct(a.confidence ?? 0)}</td>
              <td class="probs">{#each Object.entries(a.probabilities ?? {}).sort((x, y) => y[1] - x[1]).slice(0, 4) as [option, p] (option)}
                <div class="prob"><span>{option}</span><span class="bar"><i style:width={`${p * 100}%`}></i></span><span class="n">{pct(p)}</span></div>{/each}</td>
              <td>{#if label}{label} {#if !a.abstained}<span class={predicted(a) === label ? "pass" : "fail"}>{predicted(a) === label ? "✓" : "✗"}</span>{/if}{:else}<span class="muted">no label</span>{/if}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    {#if attrs.human}<p>Human approver: <strong class={attrs.human === "approved" ? "pass" : "fail"}>{String(attrs.human)}</strong>{#if attrs.violation} · {String(attrs.violation)}{/if}</p>{/if}
    <details><summary>State the policy saw</summary><CodeBlock text={pretty(span.input)} label="state" language="json" /></details>
  {:else if span.kind === "critique"}
    {@const review = (span.output ?? {}) as { verdict?: string; issues?: string[]; summary?: string }}
    <p>Verdict: <strong class={review.verdict === "accept" ? "pass" : "fail"}>{review.verdict ?? "—"}</strong></p>
    {#if review.issues?.length}<ul>{#each review.issues as issue (issue)}<li>{issue}</li>{/each}</ul>{/if}
    {#if review.summary}<p class="muted">{review.summary}</p>{/if}
  {:else}
    {#if span.input != null && pretty(span.input) !== ""}<h4>Input</h4><CodeBlock text={pretty(span.input)} label="input" />{/if}
    {#if output}
      <h4>Output {#if previous && previous !== output}
        <button class="link" onclick={() => (showDiff = !showDiff)} aria-pressed={showDiff}>{showDiff ? "show text" : "show changes vs previous"}</button>{/if}</h4>
      {#if showDiff}
        <pre class="diff">{#each diff as line, i (i)}<span class={line.kind}>{line.kind === "added" ? "+ " : line.kind === "removed" ? "− " : "  "}{line.text}
</span>{/each}</pre>
      {:else}
        <CodeBlock text={output} label="output" />
      {/if}
    {/if}
  {/if}

  {#if otherArtifacts.length}
    <h4>Files</h4>
    <div class="files">{#each otherArtifacts as artifact, i (artifact.key || `${artifact.name}-${i}`)}<ArtifactView {runId} {artifact} />{/each}</div>
  {/if}
</section>

<style>
  .span { display: grid; gap: 8px; }
  .span.nested { border-left: 3px solid var(--border); padding-left: 12px; margin-top: 8px; }
  header { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; }
  .kind { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); }
  .facts { margin-left: auto; font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
  h4 { margin: 6px 0 0; font-size: 13px; display: flex; gap: 8px; align-items: baseline; }
  .small { font-size: 12px; }
  .link { background: none; border: none; padding: 0; color: var(--accent); cursor: pointer; font-size: 12px; text-decoration: underline; }
  .fail-pill { color: var(--critical); }
  .files { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
  .probs { min-width: 180px; }
  .prob { display: grid; grid-template-columns: minmax(60px, 1fr) 70px 42px; gap: 6px; align-items: center; font-size: 12px; }
  .bar { height: 6px; background: var(--surface-3); border-radius: 3px; overflow: hidden; }
  .bar i { display: block; height: 100%; background: var(--kind-decision); }
  .diff { margin: 0; padding: 10px 12px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; max-height: 420px;
    overflow: auto; font: 12.5px/1.5 ui-monospace, monospace; white-space: pre-wrap; }
  .diff .added { color: var(--good); background: color-mix(in srgb, var(--good) 10%, transparent); display: block; }
  .diff .removed { color: var(--critical); background: color-mix(in srgb, var(--critical) 10%, transparent); display: block; text-decoration: line-through; }
  .diff .same { display: block; color: var(--text-secondary); }
</style>
