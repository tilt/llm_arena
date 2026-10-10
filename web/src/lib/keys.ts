// The key panel's rows: one per provider the runtime reports, worded for what that secret is (design 13.12).

export interface KeyRow {
  provider: string;
  source: string;
  label: string;
  placeholder: string;
  aria: string;
  warning: string;
}

const WORDING: Record<string, Omit<KeyRow, "provider" | "source">> = {
  openai: { label: "OpenAI", placeholder: "paste key", aria: "OpenAI API key", warning: "" },
  anthropic: { label: "Anthropic", placeholder: "paste key", aria: "Anthropic API key", warning: "" },
  typesafe: { label: "TypeSafe (Jev)", placeholder: "paste key", aria: "TypeSafe (Jev) API key", warning: "" },
  tavily: { label: "Tavily (live search)", placeholder: "paste key", aria: "Tavily (live search) API key", warning: "" },
  github: {
    label: "GitHub (claims)", placeholder: "paste token", aria: "GitHub token",
    warning: "This token can read, edit and delete all your gists.",
  },
};

/** Rows in the runtime's order; `providers` limits them (an inline panel asking for one missing key). */
export function keyRows(keys: Record<string, string | undefined>, providers?: string[]): KeyRow[] {
  return Object.entries(keys)
    .filter(([provider]) => !providers || providers.includes(provider))
    .map(([provider, source]) => ({
      provider, source: source ?? "missing",
      ...(WORDING[provider] ?? { label: provider, placeholder: "paste key", aria: `${provider} API key`, warning: "" }),
    }));
}
