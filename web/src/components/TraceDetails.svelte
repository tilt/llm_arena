<script lang="ts">
  import { num } from "../lib/format";
  import type { TrialRow } from "../lib/report";

  interface SpanView { kind: string; name: string; model?: string | null; error?: string | null; duration_s?: number;
    prompt_tokens?: number; completion_tokens?: number; input?: unknown; output?: unknown; attrs?: Record<string, unknown> }
  let { trial, scores, trace }: { trial: TrialRow; scores: Record<string, unknown>[]; trace: unknown } = $props();

  let open = $state(false);
  const spans = $derived(((trace as { spans?: SpanView[] } | null)?.spans ?? []) as SpanView[]);
  const clip = (value: unknown, max = 1500) => {
    if (value === null || value === undefined || value === "") return "";
    // LLM calls carry the whole conversation; the last two messages are what matters for reading.
    const shown = Array.isArray(value) ? value.slice(-2) : value;
    const text = typeof shown === "string" ? shown : JSON.stringify(shown, null, 1);
    return text.length > max ? `${text.slice(0, max)} …` : text;
  };
  const sorted = $derived([...scores].sort((a, b) => String(a.level).localeCompare(String(b.level)) || String(a.name).localeCompare(String(b.name))));
</script>

<details bind:open>
  <summary>
    <span class={trial.passed ? "pass" : "fail"}>{trial.passed ? "✓ pass" : "✗ fail"}</span>
    · {trial.scenario} · <strong>{trial.config}</strong> · {trial.task_id}{trial.repeat ? ` (rep ${trial.repeat})` : ""}
    <span class="muted">· {num(trial.duration_s, 1)}s · {trial.tokens.toLocaleString("en-US")} tok</span>
  </summary>
  {#if open}
    <div class="body">
      {#if trial.error}<pre class="fail">{trial.error}</pre>{/if}
      <div class="table-wrap">
        <table>
          <thead><tr><th>Score</th><th>Level</th><th class="n">Value</th><th>Rationale</th></tr></thead>
          <tbody>
            {#each sorted as s (`${s.name}`)}
              <tr><td>{s.name}</td><td>{s.level}</td>
                <td class="n" class:pass={s.passed === true} class:fail={s.passed === false}>{num(Number(s.value))}{s.passed === true ? " ✓" : s.passed === false ? " ✗" : ""}</td>
                <td>{s.rationale}</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
      <div class="head">Final output</div><pre>{trial.final}</pre>
      {#each spans as span, i (i)}
        <div class="head">{i + 1}. <strong>{span.kind}</strong> · {span.name}{span.model ? ` · ${span.model}` : ""} · {num(span.duration_s ?? 0)}s
          {#if span.prompt_tokens}· {span.prompt_tokens}+{span.completion_tokens} tok{/if}
          {#if span.error}<span class="fail"> · {span.error}</span>{/if}</div>
        {#if clip(span.input)}<pre>{clip(span.input)}</pre>{/if}
        {#if clip(span.output)}<pre>→ {clip(span.output)}</pre>{/if}
      {/each}
    </div>
  {/if}
</details>

<style>
  details { border-bottom: 1px solid var(--grid); }
  summary { padding: 8px 4px; font-size: 13px; }
  .body { padding: 4px 8px 16px; }
  .head { font-size: 12px; color: var(--text-secondary); margin-top: 10px; }
</style>
