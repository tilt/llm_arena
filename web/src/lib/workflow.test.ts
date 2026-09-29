import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ScenarioManifest } from "./contracts";
import { CONTROL_PARAM, REVIEW_PARAM, layout, resolve } from "./workflow";

const dir = new URL("../../../contracts/scenarios/", import.meta.url);
const manifests: ScenarioManifest[] = readdirSync(dir).map((id) => JSON.parse(readFileSync(new URL(`${id}/manifest.json`, dir), "utf8")));
const defaults = (m: ScenarioManifest) => ({
  ...Object.fromEntries(m.params.map((p) => [p.name, p.default])), [CONTROL_PARAM]: "agent", [REVIEW_PARAM]: true,
});

describe("workflows from the contracts", () => {
  it("resolve to connected graphs with the default parameters", () => {
    for (const m of manifests) {
      const flow = resolve(m.workflow!, defaults(m));
      const reached = new Set(["start"]);
      for (let i = 0; i < flow.steps.length; i++) for (const e of flow.edges) if (reached.has(e.source)) reached.add(e.target);
      expect([...reached].sort(), m.id).toEqual(flow.steps.map((s) => s.id).sort());
    }
  });

  it("follow parameters like the Python engine", () => {
    const desk = manifests.find((m) => m.id === "support_desk")!;
    const policy = resolve(desk.workflow!, { ...defaults(desk), [CONTROL_PARAM]: "policy" }).steps.map((s) => s.id);
    expect(policy).toEqual(["start", "decide", "args", "approval", "human", "tools", "reply", "review", "end"]);
    const sql = manifests.find((m) => m.id === "reflection_sql")!;
    expect(resolve(sql.workflow!, { reflection_rounds: 0, feedback: "execution" }).steps.map((s) => s.id)).toEqual(["start", "draft", "run", "end"]);
  });

  it("lays every step out without overlap", () => {
    for (const m of manifests) {
      const placed = layout(resolve(m.workflow!, defaults(m))).steps;
      const spots = new Set(placed.map((p) => `${p.x},${p.y}`));
      expect(spots.size, m.id).toBe(placed.length);
    }
  });

  it("routes edges around steps they would otherwise cross", () => {
    const sql = manifests.find((m) => m.id === "reflection_sql")!;
    const placed = layout(resolve(sql.workflow!, { reflection_rounds: 1, feedback: "execution" }));
    const revise = placed.steps.find((p) => p.step.id === "revise")!;
    const skip = placed.edges.find((e) => e.edge.source === "critique" && e.edge.target === "end")!;
    const xs = [...skip.path.matchAll(/(-?[\d.]+),/g)].map((m) => Number(m[1]));
    expect(Math.min(...xs)).toBeLessThan(revise.x); // bows left of "Revise" instead of running through it
    expect(Math.min(...placed.steps.map((p) => p.x))).toBeGreaterThanOrEqual(0);
  });
});
