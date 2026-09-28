// Turn a recorded setup (leaderboard entry) back into an editable config.
import type { ModelSpec } from "./contracts";
import { DEFAULT_ROLE, emptyConfig, type ConfigDraft } from "./builder";

type RoleSpec = { provider?: string; model?: string; reasoning_effort?: string | null; tool_mode?: string; temperature?: number | null };

/** The catalog reference for a recorded role: a curated alias when one matches its call settings, else provider:model. */
export function refFor(spec: RoleSpec, aliases: Record<string, ModelSpec>): string {
  const alias = Object.entries(aliases).find(([, a]) =>
    a.provider === spec.provider && a.model === spec.model && (a.reasoning_effort ?? null) === (spec.reasoning_effort ?? null)
    && (a.tool_mode ?? "native") === (spec.tool_mode ?? "native"));
  return alias ? alias[0] : `${spec.provider}:${spec.model}`;
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
    const ref = refFor(spec, aliases);
    if (!aliases[ref] && (spec.reasoning_effort || spec.tool_mode === "json")) exact = false; // settings without an alias
    bound[role] = ref;
  }
  config.roles = { [DEFAULT_ROLE]: "" };
  config.scenarioRoles = { [scenario]: bound };
  config.scenarioParams = { [scenario]: (setup.params ?? {}) as Record<string, unknown> };
  config.decisions = (setup.decisions ?? null) as ConfigDraft["decisions"];
  return { config, exact };
}
