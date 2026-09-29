// Scenario workflows: resolve the variant that runs with given parameters (mirrors scenarios/workflow.py)
// and lay it out top to bottom for the diagram.
import type { Condition, Workflow, WorkflowEdge, WorkflowStep } from "./contracts";

export const CONTROL_PARAM = "control";
export const REVIEW_PARAM = "review";

export function holds(condition: Condition, params: Record<string, unknown>): boolean {
  const value = params[condition.param];
  const equals = condition.equals as unknown;
  if (equals !== null && equals !== undefined && value !== equals) return false;
  if (condition.one_of && !condition.one_of.includes(value)) return false;
  if (condition.gt !== null && condition.gt !== undefined && !(typeof value === "number" && value > condition.gt)) return false;
  return true;
}

export function resolve(workflow: Workflow, params: Record<string, unknown>): Workflow {
  const steps = workflow.steps.filter((s) => (s.when ?? []).every((c) => holds(c, params)));
  const kept = new Set(steps.map((s) => s.id));
  const edges = workflow.edges.filter(
    (e) => kept.has(e.source) && kept.has(e.target) && !(e.unless && kept.has(e.unless)) && (e.when ?? []).every((c) => holds(c, params)),
  );
  return { steps, edges };
}

/** Roles a step calls: its own plus fallbacks it may escalate to. */
export const stepRoles = (step: WorkflowStep): string[] => [...(step.role ? [step.role] : []), ...(step.also ?? [])];

export interface PlacedStep { step: WorkflowStep; x: number; y: number; rank: number }
export interface PlacedEdge { edge: WorkflowEdge; path: string; labelX: number; labelY: number; anchor: "start" | "middle" | "end" }
export interface Layout { steps: PlacedStep[]; edges: PlacedEdge[]; width: number; height: number }

export const NODE_W = 190;
export const NODE_H = 58;
const GAP_X = 36;
const GAP_Y = 54;
const LOOP_LANE = 150; // room on the right for return arcs and their labels
const SIDE_LANE = 170; // room on the left for edges that bow around a step (and their labels), when needed

/** Rank = longest path from the start over forward edges; each rank is one row, loops arc on the right. */
export function layout(flow: Workflow): Layout {
  const rank = new Map(flow.steps.map((s) => [s.id, 0]));
  const forward = flow.edges.filter((e) => !e.loop);
  for (let i = 0; i < flow.steps.length; i++) {
    for (const e of forward) rank.set(e.target, Math.max(rank.get(e.target)!, rank.get(e.source)! + 1));
  }
  // The result gets a row of its own, so return arcs from the last steps never cross it.
  rank.set("end", Math.max(...flow.steps.filter((s) => s.id !== "end").map((s) => rank.get(s.id)!)) + 1);
  const rows: WorkflowStep[][] = [];
  for (const s of flow.steps) (rows[rank.get(s.id)!] ??= []).push(s);
  // Place each step under the mean x of its predecessors (barycenter), then push apart where steps would
  // overlap: branches keep their column, so edges rarely cut through other steps.
  const pitch = NODE_W + GAP_X;
  const centre = new Map<string, number>();
  rows.forEach((row) => {
    const want = (s: WorkflowStep) => {
      const parents = forward.filter((e) => e.target === s.id && centre.has(e.source)).map((e) => centre.get(e.source)!);
      return parents.length ? parents.reduce((a, b) => a + b, 0) / parents.length : 0;
    };
    const wanted = new Map(row.map((s) => [s.id, want(s)]));
    row.sort((a, b) => wanted.get(a.id)! - wanted.get(b.id)!);
    const xs = row.map((s) => wanted.get(s.id)!);
    for (let i = 1; i < xs.length; i++) xs[i] = Math.max(xs[i]!, xs[i - 1]! + pitch);
    const drift = (xs.reduce((a, b) => a + b, 0) - row.reduce((a, s) => a + wanted.get(s.id)!, 0)) / xs.length;
    row.forEach((s, i) => centre.set(s.id, xs[i]! - drift));
  });
  const minX = Math.min(...centre.values()) - NODE_W / 2;
  const maxX = Math.max(...centre.values()) + NODE_W / 2;
  const rankOf = new Map(rows.flatMap((row, r) => row.map((step) => [step.id, r] as const)));
  const left = (id: string) => centre.get(id)! - NODE_W / 2 - minX; // before the side lane is known
  // A forward edge that skips rows bows around the steps in its way (on the left, where its label fits too).
  const blocked = (edge: WorkflowEdge) => {
    const a = rankOf.get(edge.source)!, b = rankOf.get(edge.target)!;
    const mid = (centre.get(edge.source)! + centre.get(edge.target)!) / 2;
    return !edge.loop && b - a > 1 && flow.steps.some((s) =>
      rankOf.get(s.id)! > a && rankOf.get(s.id)! < b && Math.abs(centre.get(s.id)! - mid) < NODE_W / 2 + 8);
  };
  const sideLane = flow.edges.some(blocked) ? SIDE_LANE : 0;
  const width = sideLane + maxX - minX + LOOP_LANE;
  const placed = new Map<string, PlacedStep>();
  rows.forEach((row, r) =>
    row.forEach((step) => placed.set(step.id, { step, rank: r, x: sideLane + left(step.id), y: r * (NODE_H + GAP_Y) })));
  const height = rows.length * (NODE_H + GAP_Y) - GAP_Y;
  let loops = 0;
  const edges = flow.edges.map((edge): PlacedEdge => {
    const a = placed.get(edge.source)!;
    const b = placed.get(edge.target)!;
    if (edge.loop || b.rank <= a.rank) {
      // Return arc: leave on the right, run up the loop lane, re-enter on the right.
      const lane = width - LOOP_LANE + 16 + (loops++ % 4) * 14;
      const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2 + 6, x2 = b.x + NODE_W, y2 = b.y + NODE_H / 2 - 6;
      return { edge, path: `M${x1},${y1} C${lane},${y1} ${lane},${y2} ${x2},${y2}`, labelX: lane + 2, labelY: (y1 + y2) / 2, anchor: "start" };
    }
    if (blocked(edge)) {
      // Leave from the step's left side, run down the side lane, enter the target from above.
      const lane = Math.min(a.x, b.x) - 28; // close to the column; the label runs left of the curve
      const x1 = a.x, y1 = a.y + NODE_H / 2, x2 = b.x + NODE_W / 2, y2 = b.y;
      return { edge, path: `M${x1},${y1} C${lane},${y1} ${lane},${y2 - 24} ${x2},${y2}`, labelX: lane - 4, labelY: (y1 + y2) / 2, anchor: "end" };
    }
    const x1 = a.x + NODE_W / 2, y1 = a.y + NODE_H, x2 = b.x + NODE_W / 2, y2 = b.y;
    const bend = (y2 - y1) / 2;
    return { edge, path: `M${x1},${y1} C${x1},${y1 + bend} ${x2},${y2 - bend} ${x2},${y2}`, labelX: (x1 + x2) / 2, labelY: (y1 + y2) / 2, anchor: "middle" };
  });
  return { steps: [...placed.values()], edges, width, height };
}
