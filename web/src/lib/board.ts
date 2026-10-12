// The claims board page's data: load board.json, choose tabs and feeds, and word rows (docs/designs/claims-board.md §9).
import type { Board as RawBoard, OverallEntry as RawEntry, Row as RawRow, RowNote as RawNote, ScenarioBoard as RawScenario, StepResult } from "./contracts";
import { pct } from "./format";
import { roleLinesOf } from "./leaderboard";
import { REPO_URL } from "./wiki";

export const BOARD_VERSION = 1;
export const PAGES_BOARD = "https://tilt.github.io/llm_arena/#/board";
export const OVERALL = "overall";
export type Feed = "reproduced" | "merged";
export type Group = "all" | "tool_calling" | "code" | "writing" | "critique" | "planning" | "vision" | "decision";

export const GROUPS: { id: Group; label: string; token: string }[] = [
  { id: "all", label: "All roles", token: "--text-secondary" },
  { id: "tool_calling", label: "Tool calling", token: "--kind-tool" },
  { id: "code", label: "Code", token: "--kind-code" },
  { id: "writing", label: "Writing", token: "--kind-human" },
  { id: "critique", label: "Critique", token: "--kind-check" },
  { id: "planning", label: "Planning", token: "--seq-2" },
  { id: "vision", label: "Vision", token: "--seq-4" },
  { id: "decision", label: "Decision", token: "--kind-decision" },
];

// board.json as the page uses it: every field present (the schema marks defaulted fields optional).
export type RowNote = Required<RawNote>;
export type Row = Omit<Required<RawRow>, "notes" | "criteria"> & { notes: RowNote[]; criteria: Record<string, StepResult> | null };
export type OverallEntry = Required<RawEntry>;
export type ScenarioBoard = Omit<Required<RawScenario>, "ranked" | "unreproduced" | "older"> & { ranked: Row[]; unreproduced: Row[]; older: Row[] };
export type Board = Omit<Required<RawBoard>, "scenarios" | "overall"> & {
  scenarios: ScenarioBoard[];
  overall: Partial<Record<Feed, Partial<Record<Group, OverallEntry[]>>>>;
};

function rowOf(raw: RawRow): Row {
  return {
    runnable: true, decisions: null, judge: null, reproducers: [], ...raw,
    criteria: (raw.criteria as Record<string, StepResult> | null | undefined) ?? null,
    notes: (raw.notes ?? []).map((note) => ({ count: 0, detail: "", ...note })),
  } as Row;
}

/** Fill every defaulted field once, so the page never handles a missing one. */
export function normalize(raw: RawBoard): Board {
  return {
    delisted: [], ledger_lines: 0, ledger_head: "", registry_entries: 0, registry_head: "", ...raw,
    board_version: raw.board_version ?? 0,
    overall: (raw.overall ?? {}) as Board["overall"],
    scenarios: (raw.scenarios ?? []).map((s) => ({
      ...s, merged: s.merged ?? [], ranked: (s.ranked ?? []).map(rowOf), unreproduced: (s.unreproduced ?? []).map(rowOf),
      older: (s.older ?? []).map(rowOf),
    })),
  } as Board;
}

export type BoardLoad =
  | { state: "ok"; board: Board }
  | { state: "missing" }
  | { state: "outdated" }
  | { state: "error"; message: string };

/** board.json from this site (Pages builds it in); a newer format than this page knows asks for a reload. */
export async function loadBoard(base: string, fetcher: typeof fetch = fetch): Promise<BoardLoad> {
  try {
    const response = await fetcher(`${base}board.json`, { cache: "no-cache" });
    if (response.status === 404) return { state: "missing" };
    if (!response.ok) return { state: "error", message: `the board couldn't be loaded (${response.status})` };
    const raw = (await response.json()) as RawBoard;
    if (typeof raw !== "object" || raw === null || !Array.isArray(raw.scenarios)) return { state: "outdated" };
    return raw.board_version === BOARD_VERSION ? { state: "ok", board: normalize(raw) } : { state: "outdated" };
  } catch {
    return { state: "error", message: "the board couldn't be loaded; check your connection" };
  }
}

/** Plain #/board opens the scenario with the most reproduced claims (ties: most claims, then name) (design 3A). */
export function defaultTab(board: Board): string {
  const ranked = [...board.scenarios].sort((a, b) =>
    b.ranked.length - a.ranked.length || (b.ranked.length + b.unreproduced.length) - (a.ranked.length + a.unreproduced.length)
    || a.scenario.localeCompare(b.scenario));
  return ranked[0]?.scenario ?? OVERALL;
}

export const scenarioOf = (board: Board, tab: string | undefined): ScenarioBoard | undefined =>
  board.scenarios.find((s) => s.scenario === tab);

// ---- the merge switch, remembered per scenario (design 13A) -------------------------------------------------------
const feedKey = (tab: string) => `arena.board.feed.${tab}`;

export function defaultFeed(board: Board, tab: string): Feed {
  const scenario = scenarioOf(board, tab);
  const reproduced = scenario ? scenario.ranked.length > 0 : board.scenarios.some((s) => s.ranked.length > 0);
  return reproduced ? "reproduced" : "merged";
}

export function storedFeed(tab: string, storage: Pick<Storage, "getItem"> | undefined = globalThis.localStorage): Feed | null {
  try {
    const value = storage?.getItem(feedKey(tab));
    return value === "reproduced" || value === "merged" ? value : null;
  } catch {
    return null;
  }
}

export function saveFeed(tab: string, feed: Feed, storage: Pick<Storage, "setItem"> | undefined = globalThis.localStorage): void {
  try {
    storage?.setItem(feedKey(tab), feed);
  } catch {
    // a convenience only: private windows and blocked storage just keep the default
  }
}

/** The rows a scenario tab shows in a feed: ranked ones, or both lists in one ranking (the chart shows the same). */
export function rowsOf(scenario: ScenarioBoard, feed: Feed): Row[] {
  if (feed === "reproduced") return scenario.ranked;
  const all = new Map([...scenario.ranked, ...scenario.unreproduced].map((row) => [row.claim_hash, row]));
  return scenario.merged.map((hash) => all.get(hash)).filter((row): row is Row => row !== undefined);
}

// ---- words -----------------------------------------------------------------------------------------------------------
/** "gpt-4.1-mini + claude-haiku-4.5": each model once, in role order. */
export function setupText(row: Row): string {
  return [...new Set(roleLinesOf({ roles: row.roles }).map((line) => line.model))].join(" + ");
}

export const interval = (row: Row) => `${pct(row.rate)} [${Math.round(row.low * 100)}–${Math.round(row.high * 100)}]`;

/** The answer line under the title (design 2A): the scenario's rank 1 in words, or the call for reproductions. */
export function answerLine(scenario: ScenarioBoard): string {
  const best = scenario.ranked[0];
  if (!best) {
    const n = scenario.unreproduced.length;
    return `No reproduced claims yet: the ${n} claim${n === 1 ? "" : "s"} below wait${n === 1 ? "s" : ""} for a first reproduction.`;
  }
  return `Best reproduced on ${scenario.scenario}: ${setupText(best)}, ${interval(best)}, reproduced by ${best.people} ${best.people === 1 ? "person" : "people"}.`;
}

export const tierText = (row: Row) =>
  row.tier === "verified" ? `verified · ${row.people} people` : row.tier === "reproduced" ? `reproduced · ${row.people}` : "claimed";

/** Who reproduced it, shown on the row (the visible answer to sock-puppet accounts, design R2-4). */
export const BY_SHOWN = 3;
export function byText(row: Row): string {
  const names = row.reproducers.slice(0, BY_SHOWN).join(", ");
  const more = row.reproducers.length - BY_SHOWN;
  return more > 0 ? `${names} and ${more} more` : names;
}

export function noteText(note: RowNote): string {
  switch (note.kind) {
    case "removed_after_recorded":
      return `${note.count} reproduction${note.count === 1 ? "" : "s"} removed by the author after the board recorded ${note.count === 1 ? "it" : "them"} (still counted)`;
    case "edited_after_recorded":
      return `${note.count} reproduction${note.count === 1 ? " was" : "s were"} edited after the board recorded ${note.count === 1 ? "it" : "them"}; the recorded version counts`;
    case "removed_referenced":
      return `${note.count} reproduction${note.count === 1 ? "" : "s"} referenced by later ones ${note.count === 1 ? "was" : "were"} removed before the board saw ${note.count === 1 ? "it" : "them"}`;
    case "gist_deleted":
      return "gist deleted by its author";
    case "not_refreshed":
      return `not refreshed since ${note.detail.slice(0, 16).replace("T", " ")} UTC`;
    case "not_runnable":
      return `no longer runnable: ${note.detail}`;
    case "partial_thread":
      return `based on the first ${note.count} of ${note.detail} comments`;
    default:
      return "";
  }
}

/** Rows whose claim page can't load or run say so, and their links are disabled. */
export const linkable = (row: Row) => row.runnable && !row.notes.some((n) => n.kind === "gist_deleted");
export const claimHref = (row: Row) => `#/claim/gist/${row.gist_id}@${row.revision}`;

export function submitHref(gistId: string, revision: string): string {
  const query = new URLSearchParams({ template: "claim.yml", gist: gistId, revision });
  return `${REPO_URL}/issues/new?${query}`;
}
export const SUBMIT_FORM = `${REPO_URL}/issues/new?template=claim.yml`;

// ---- overall ---------------------------------------------------------------------------------------------------------
export function overallOf(board: Board, feed: Feed, group: Group): OverallEntry[] {
  return board.overall[feed]?.[group] ?? [];
}

export const entryLabel = (entry: OverallEntry) =>
  `${entry.model}${entry.reasoning_effort ? ` (${entry.reasoning_effort === "none" ? "no thinking" : `${entry.reasoning_effort} reasoning`})` : ""}${entry.tool_mode === "json" ? " (json tools)" : ""}`;

export const gapText = (entry: OverallEntry) =>
  entry.score > -0.005 ? "level with the best, on average" : `${Math.round(-entry.score * 100)} pts behind the best, on average`;

// ---- timing ----------------------------------------------------------------------------------------------------------
export const isStale = (board: Board, now: Date) => now.getTime() - Date.parse(board.built_at) > 24 * 3600_000;

/** About when the next scheduled build runs (every 6 hours at :17 UTC); an estimate, GitHub can delay it. */
export function nextUpdate(board: Board, now: Date): Date {
  const next = new Date(Math.max(now.getTime(), Date.parse(board.built_at)));
  next.setUTCMinutes(17, 0, 0);
  while (next.getUTCHours() % 6 !== 0 || next.getTime() <= now.getTime()) next.setUTCHours(next.getUTCHours() + 1);
  return next;
}
