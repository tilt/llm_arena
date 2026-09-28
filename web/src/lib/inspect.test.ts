import { describe, expect, it } from "vitest";

import type { Span } from "./contracts";
import { conversation, executions, images, lineDiff, stepStats } from "./inspect";

const span = (step: string | null, parent: number | null, extra: Partial<Span> = {}): Span =>
  ({ kind: "step", name: step ?? "x", step, parent, ...extra }) as Span;

describe("step executions", () => {
  // critique (0) → llm call (1); revise (2) → llm (3) → nested tool (4, other step); critique again (5) → llm (6)
  const spans = [
    span("critique", null, { kind: "critique" }), span("critique", 0, { kind: "llm_call", prompt_tokens: 10, completion_tokens: 5 }),
    span("revise", null), span("revise", 2, { kind: "llm_call" }), span("run", 3, { kind: "tool_call", attrs: { ok: false } }),
    span("critique", null, { kind: "critique" }), span("critique", 5, { kind: "llm_call", error: "timeout" }),
  ];

  it("groups nested spans of the same step under their execution", () => {
    const critiques = executions(spans, "critique");
    expect(critiques.map((e) => [e.index, e.children.map((c) => c.index)])).toEqual([[0, [1]], [5, [6]]]);
    expect(executions(spans, "run").map((e) => e.index)).toEqual([4]); // a tool call inside revise is its own step
  });

  it("counts executions, errors and tokens per step", () => {
    const stats = stepStats(spans);
    expect(stats.critique).toMatchObject({ runs: 2, errors: 1, tokens: 15 });
    expect(stats.run).toMatchObject({ runs: 1, errors: 1 });
  });
});

describe("conversation view", () => {
  it("shows what is new since the model's last turn", () => {
    const input = [
      { role: "system", content: "rules" }, { role: "user", content: "task" }, { role: "assistant", content: "call" },
      { role: "tool", content: "result" }, { role: "user", content: [{ type: "text", text: "look" }, { type: "image_url", image_url: { url: "artifact:t/001-input-image.png" } }] },
    ];
    const view = conversation(input);
    expect(view.system).toBe("rules");
    expect(view.earlier).toBe(2);
    expect(view.latest.map((m) => m.role)).toEqual(["tool", "user"]);
    expect(images(view.latest[1]!.content)).toEqual(["t/001-input-image.png"]);
  });
});

describe("revision diff", () => {
  it("marks changed lines", () => {
    expect(lineDiff("a\nb\nc", "a\nB\nc")).toEqual([
      { kind: "same", text: "a" }, { kind: "removed", text: "b" }, { kind: "added", text: "B" }, { kind: "same", text: "c" },
    ]);
  });
});
