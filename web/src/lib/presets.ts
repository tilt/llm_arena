// Model presets in the UI: step kinds, model references with call settings, and the preset new setups start from.
import type { CatalogItem } from "./backend";
import type { ModelPreset } from "./contracts";

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
  { value: "low", label: "low effort" },
  { value: "medium", label: "medium effort" },
  { value: "high", label: "high effort" },
];

/** The thinking settings a model accepts (engine: llm/reasoning.py). OpenAI and Ollama take an effort, where "none"
 *  switches thinking off; Anthropic takes an effort but no "off"; LM Studio ignores the setting, and models that do not
 *  think have nothing to set. A model missing from the catalog keeps every option, so a saved setting stays visible. */
export function thinkingLevels(base: string, item?: CatalogItem): typeof THINKING {
  if (!base) return [];
  if (!item) return THINKING;
  if (!item.spec.capabilities?.reasoning) return [];
  if (item.spec.provider === "openai" || item.spec.provider === "ollama") return THINKING;
  if (item.spec.provider === "anthropic") return THINKING.filter((t) => t.value !== "none");
  return [];
}

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

/** A step binding that keeps the model the step inherits (preset, fallback step, default) and changes only its
 *  thinking: "#reasoning=low". It keeps following the preset when that changes. The engine takes concrete references
 *  only, so toExperiment resolves these with applyOverride. "#reasoning=default" means the model's own default. */
export function isOverride(ref: string): boolean {
  return ref.startsWith("#");
}

export function thinkingOverride(reasoning: string): string {
  return `#reasoning=${reasoning || "default"}`;
}

/** The thinking an override sets ("" = the model's default). */
export function overrideReasoning(ref: string): string {
  const { reasoning } = splitRef(ref);
  return reasoning === "default" ? "" : reasoning;
}

/** The concrete reference a binding stands for: an override applied to the inherited reference
 *  ("#reasoning=low" on "ollama:qwen3:4b#reasoning=none" -> "ollama:qwen3:4b#reasoning=low"); "" when there is
 *  nothing to inherit. Any other binding is already concrete. */
export function applyOverride(ref: string, inherited: string): string {
  if (!isOverride(ref)) return ref;
  const from = splitRef(inherited);
  if (!from.base) return "";
  const { rest } = splitRef(ref);
  const keys = new Set(rest.map((s) => s.split("=")[0]));
  return joinRef(from.base, overrideReasoning(ref), [...from.rest.filter((s) => !keys.has(s.split("=")[0])), ...rest]);
}

/** Short human label: "qwen3:4b · thinking off". */
export function describeRef(ref: string): string {
  const { base, reasoning, rest } = splitRef(ref);
  const model = base.includes(":") ? base.slice(base.indexOf(":") + 1) : base;
  const notes = [reasoning === "none" ? "thinking off" : reasoning ? `${reasoning} reasoning` : "", ...rest].filter(Boolean);
  return notes.length ? `${model} · ${notes.join(", ")}` : model;
}

/** Which model a preset gives a role of this kind (profiles without the kind fall back to their text model). */
export function modelFor(profile: ModelPreset | undefined, kind: string): string {
  if (!profile) return "";
  const models = profile.models as Record<string, string | undefined>;
  return models[kind] || models.text || Object.values(models).find(Boolean) || "";
}

const ACTIVE = "llm-arena.preset";
const EDITED = "llm-arena.presets";
// Before the rename these were "llm-arena.baseline(s)": read them once so nobody loses a choice or an edit.
const read = (key: string, old: string) => localStorage.getItem(key) ?? localStorage.getItem(old);

/** The preset new setups start from (a per-browser preference). */
export function activePreset(): string {
  try { return read(ACTIVE, "llm-arena.baseline") ?? "local-small"; } catch { return "local-small"; }
}
export function setActivePreset(name: string): void {
  try { localStorage.setItem(ACTIVE, name); } catch { /* preference only */ }
}

/** Browser mode keeps edited presets in local storage (the local app saves them on the server). */
export function editedPresets(): Record<string, ModelPreset> {
  try { return JSON.parse(read(EDITED, "llm-arena.baselines") ?? "{}") as Record<string, ModelPreset>; } catch { return {}; }
}
export function storeEditedPresets(presets: Record<string, ModelPreset>): void {
  localStorage.setItem(EDITED, JSON.stringify(presets));
}

/** Providers a web page can call directly (browser mode). Local servers and Ollaya/Jev are out of reach. */
export const BROWSER_PROVIDERS = ["openai", "anthropic"];

/** Presets whose every model runs in this runtime; dedicated decision services are dropped in the browser. */
export function usablePresets(presets: Record<string, ModelPreset>, browser: boolean): Record<string, ModelPreset> {
  if (!browser) return presets;
  const runs = (ref: string) => BROWSER_PROVIDERS.includes(ref.split(":")[0] ?? "");
  return Object.fromEntries(Object.entries(presets)
    .filter(([, p]) => Object.values(p.models).every((ref) => !ref || runs(ref)))
    .map(([name, p]) => [name, { ...p, decision_service: null }]));
}

/** The active preset if it is usable here, else the first usable one ("" when none is). */
export function usableActive(presets: Record<string, ModelPreset>): string {
  const active = activePreset();
  return presets[active] ? active : Object.keys(presets)[0] ?? "";
}
