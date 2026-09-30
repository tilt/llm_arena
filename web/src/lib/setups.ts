// Turn a recorded setup (leaderboard entry) back into an editable config.
import type { ModelSpec } from "./contracts";
import { DEFAULT_ROLE, emptyConfig, suggestName, type ConfigDraft } from "./builder";

type RoleSpec = { provider?: string; model?: string; reasoning_effort?: string | null; tool_mode?: string; temperature?: number | null };

/** The reference for a recorded role: a curated alias when one matches its call settings, else provider:model with
 *  the settings after "#" ("ollama:qwen3:4b#reasoning=none"), so thinking and tool mode carry over either way. */
export function refFor(spec: RoleSpec, aliases: Record<string, ModelSpec>): string {
  const alias = Object.entries(aliases).find(([, a]) =>
    a.provider === spec.provider && a.model === spec.model && (a.reasoning_effort ?? null) === (spec.reasoning_effort ?? null)
    && (a.tool_mode ?? "native") === (spec.tool_mode ?? "native"));
  if (alias) return alias[0];
  const settings = [...(spec.reasoning_effort ? [`reasoning=${spec.reasoning_effort}`] : []), ...(spec.tool_mode === "json" ? ["tools=json"] : [])];
  return `${spec.provider}:${spec.model}${settings.length ? `#${settings.join(",")}` : ""}`;
}

export function configFromSetup(
  scenario: string, name: string, setup: Record<string, unknown>, aliases: Record<string, ModelSpec>,
): { config: ConfigDraft; exact: boolean } {
  const config = { ...emptyConfig(0), name };
  const roles = (setup.roles ?? {}) as Record<string, RoleSpec | string>;
  let exact = true;
  const bound: Record<string, string> = {};
  for (const [role, spec] of Object.entries(roles)) {
    if (typeof spec === "string") { bound[role] = spec; exact = false; continue; }
    bound[role] = refFor(spec, aliases);
  }
  config.roles = { [DEFAULT_ROLE]: "" };
  config.scenarioRoles = { [scenario]: bound };
  config.scenarioParams = { [scenario]: (setup.params ?? {}) as Record<string, unknown> };
  config.decisions = (setup.decisions ?? null) as ConfigDraft["decisions"];
  return { config, exact };
}

/** The name a recorded setup suggests (what actually ran), like suggestName for a setup being built. */
export function nameFromSetup(setup: Record<string, unknown>): string {
  const roles = (setup.roles ?? {}) as Record<string, RoleSpec | string>;
  const refs = Object.fromEntries(Object.entries(roles).map(([role, spec]) => [role, typeof spec === "string" ? spec
    : `${spec.provider}:${spec.model}${spec.reasoning_effort ? `#reasoning=${spec.reasoning_effort}` : ""}`]));
  return suggestName({ ...emptyConfig(0), roles: refs, decisions: (setup.decisions ?? null) as ConfigDraft["decisions"] }, {});
}
