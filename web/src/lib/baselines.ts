// Baseline profiles in the UI: step kinds, model references with call settings, and the profile new setups start from.
import type { BaselineProfile } from "./contracts";

export type Kind = "text" | "vision" | "code" | "agent" | "decision";

export const KINDS: { kind: Kind; label: string; hint: string }[] = [
  { kind: "text", label: "Text", hint: "prompt → text: writers, critics, planners" },
  { kind: "vision", label: "Vision", hint: "image + prompt → text: critics that look at charts" },
  { kind: "code", label: "Code", hint: "prompt → code: SQL, Python, plotting code" },
  { kind: "agent", label: "Agent", hint: "tool use: picks tools and arguments over many turns" },
  { kind: "decision", label: "Decision", hint: "prompt → decision: next action, approval, review (LLM decider)" },
];

export const THINKING = [
  { value: "", label: "model default" },
  { value: "none", label: "thinking off" },
  { value: "low", label: "low" },
  { value: "medium", label: "medium" },
  { value: "high", label: "high" },
];

/** "ollama:qwen3:4b#reasoning=none" -> { base: "ollama:qwen3:4b", reasoning: "none" } (other settings are kept). */
export function splitRef(ref: string): { base: string; reasoning: string; rest: string[] } {
  const [base = "", settings = ""] = ref.split("#", 2);
  const parts = settings.split(",").filter(Boolean);
  const reasoning = parts.find((p) => p.startsWith("reasoning="))?.slice("reasoning=".length) ?? "";
  return { base, reasoning, rest: parts.filter((p) => !p.startsWith("reasoning=")) };
}

export function joinRef(base: string, reasoning: string, rest: string[] = []): string {
  const settings = [...(reasoning ? [`reasoning=${reasoning}`] : []), ...rest];
  return settings.length && base ? `${base}#${settings.join(",")}` : base;
}

/** Short human label: "qwen3:4b · thinking off". */
export function describeRef(ref: string): string {
  const { base, reasoning, rest } = splitRef(ref);
  const model = base.includes(":") ? base.slice(base.indexOf(":") + 1) : base;
  const notes = [reasoning === "none" ? "thinking off" : reasoning ? `${reasoning} reasoning` : "", ...rest].filter(Boolean);
  return notes.length ? `${model} · ${notes.join(", ")}` : model;
}

/** Which model a profile gives a role of this kind (profiles without the kind fall back to their text model). */
export function modelFor(profile: BaselineProfile | undefined, kind: string): string {
  if (!profile) return "";
  const models = profile.models as Record<string, string | undefined>;
  return models[kind] || models.text || Object.values(models).find(Boolean) || "";
}

const ACTIVE = "llm-arena.baseline";
const EDITED = "llm-arena.baselines";

/** The profile new setups start from (a per-browser preference). */
export function activeBaseline(): string {
  try { return localStorage.getItem(ACTIVE) ?? "local-small"; } catch { return "local-small"; }
}
export function setActiveBaseline(name: string): void {
  try { localStorage.setItem(ACTIVE, name); } catch { /* preference only */ }
}

/** Browser mode keeps edited profiles in local storage (the local app saves them on the server). */
export function editedProfiles(): Record<string, BaselineProfile> {
  try { return JSON.parse(localStorage.getItem(EDITED) ?? "{}") as Record<string, BaselineProfile>; } catch { return {}; }
}
export function storeEditedProfiles(profiles: Record<string, BaselineProfile>): void {
  localStorage.setItem(EDITED, JSON.stringify(profiles));
}
