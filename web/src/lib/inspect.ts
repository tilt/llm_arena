// Pure helpers for the step inspector: group a trial's spans by workflow step and prepare them for display.
import type { ScenarioManifest, Span, Workflow } from "./contracts";
import { CONTROL_PARAM, REVIEW_PARAM, resolve } from "./workflow";

export interface Execution {
  span: Span;
  index: number; // position in the trace
  children: { span: Span; index: number }[]; // nested spans of the same step (e.g. the LLM call inside a critique)
}

export interface StepStats {
  runs: number;
  errors: number;
  tokens: number;
  costUsd: number;
  seconds: number;
}

/** The outermost ancestor of a span that still belongs to the same step (the span itself if none). */
function rootOf(spans: Span[], index: number): number {
  let current = index;
  for (;;) {
    const parent = spans[current]?.parent ?? null;
    if (parent === null || spans[parent]?.step !== spans[index]?.step) return current;
    current = parent;
  }
}

/** A step's executions in order: each top-level span of the step, with its nested spans of the same step. */
export function executions(spans: Span[], step: string): Execution[] {
  const byRoot = new Map<number, Execution>();
  spans.forEach((span, index) => {
    if (span.step !== step) return;
    const root = rootOf(spans, index);
    if (root === index) byRoot.set(index, { span, index, children: [] });
    else byRoot.get(root)?.children.push({ span, index });
  });
  return [...byRoot.values()];
}

export function stepStats(spans: Span[]): Record<string, StepStats> {
  const stats: Record<string, StepStats> = {};
  spans.forEach((span, index) => {
    if (!span.step) return;
    const s = (stats[span.step] ??= { runs: 0, errors: 0, tokens: 0, costUsd: 0, seconds: 0 });
    if (rootOf(spans, index) === index) {
      s.runs += 1;
      s.seconds += span.duration_s ?? 0;
    }
    if (span.error || span.attrs?.ok === false) s.errors += 1;
    if (span.kind === "llm_call") {
      s.tokens += (span.prompt_tokens ?? 0) + (span.completion_tokens ?? 0);
      s.costUsd += span.cost_usd ?? 0;
    }
  });
  return stats;
}

export type Message = { role?: string; content?: unknown; tool_calls?: unknown };

/** What a model call newly received: the system prompt, the number of earlier messages, and the messages after
 *  the model's last turn (the new prompt, tool results, observations). */
export function conversation(input: unknown): { system: string; earlier: number; latest: Message[]; all: Message[] } {
  const all = (Array.isArray(input) ? input : []) as Message[];
  const system = all.filter((m) => m.role === "system").map((m) => text(m.content)).join("\n\n");
  const lastAssistant = all.map((m) => m.role).lastIndexOf("assistant");
  const latest = all.slice(lastAssistant + 1).filter((m) => m.role !== "system");
  const earlier = all.filter((m) => m.role !== "system").length - latest.length;
  return { system, earlier, latest, all };
}

/** Text of a message's content; image parts become "[image]" (the UI shows them via `images`). */
export function text(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part: { type?: string; text?: string }) => (part.type === "text" ? part.text ?? "" : part.type === "image_url" ? "[image]" : ""))
      .join("\n");
  }
  return content == null ? "" : JSON.stringify(content, null, 2);
}

/** Artifact keys referenced from image parts (artifact:<key>). */
export function images(content: unknown): string[] {
  if (!Array.isArray(content)) return [];
  return content
    .filter((part: { type?: string }) => part.type === "image_url")
    .map((part: { image_url?: { url?: string } }) => part.image_url?.url ?? "")
    .filter((url) => url.startsWith("artifact:"))
    .map((url) => url.slice("artifact:".length));
}

/** The workflow as this trial ran it: scenario defaults, the trial's parameters and its control policy. */
export function trialWorkflow(manifest: ScenarioManifest, trial: Record<string, unknown>): Workflow | null {
  if (!manifest.workflow) return null;
  const params = parse(trial.params_json);
  const setup = parse(trial.setup_json);
  const decisions = (setup.decisions ?? null) as { control?: string; review?: boolean } | null;
  return resolve(manifest.workflow, {
    ...Object.fromEntries(manifest.params.map((p) => [p.name, p.default])),
    ...params,
    [CONTROL_PARAM]: decisions ? decisions.control ?? "policy" : "agent",
    [REVIEW_PARAM]: decisions?.review ?? true,
  });
}

function parse(value: unknown): Record<string, unknown> {
  if (typeof value !== "string" || !value) return {};
  try {
    return JSON.parse(value) as Record<string, unknown>;
  } catch {
    return {};
  }
}

export type DiffLine = { kind: "same" | "added" | "removed"; text: string };

/** Line diff (LCS) for "what changed in this revision"; very large inputs fall back to a full replacement. */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");
  if (a.length * b.length > 250_000) {
    return [...a.map((t) => ({ kind: "removed" as const, text: t })), ...b.map((t) => ({ kind: "added" as const, text: t }))];
  }
  const lcs = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i]![j] = a[i] === b[j] ? lcs[i + 1]![j + 1]! + 1 : Math.max(lcs[i + 1]![j]!, lcs[i]![j + 1]!);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ kind: "same", text: a[i]! });
      i++;
      j++;
    } else if (lcs[i + 1]![j]! >= lcs[i]![j + 1]!) {
      out.push({ kind: "removed", text: a[i++]! });
    } else {
      out.push({ kind: "added", text: b[j++]! });
    }
  }
  while (i < a.length) out.push({ kind: "removed", text: a[i++]! });
  while (j < b.length) out.push({ kind: "added", text: b[j++]! });
  return out;
}
