// Named OpenAI-compatible endpoints (vLLM, llama.cpp, LiteLLM, …): the rules the engine applies (llm/spec.py), checked
// in the form before anything is sent, and the hints a failed listing needs.
import type { CatalogItem } from "./backend";

const ID = /^[a-z0-9][a-z0-9-]{0,31}$/;
// An endpoint id is the prefix of its model references ("gpu-box:qwen3"), so it may not shadow a provider or a
// decision service.
const RESERVED = ["openai", "anthropic", "ollama", "lmstudio", "ollaya", "jev", "typesafe", "tavily"];

/** Why an id is not usable, or "" when it is. */
export function endpointIdProblem(id: string): string {
  if (!ID.test(id)) return "Use 1–32 lowercase letters, digits or “-”, starting with a letter or digit.";
  if (RESERVED.includes(id)) return `“${id}” is reserved; choose another name.`;
  return "";
}

/** Why a base URL is not usable, or "" when it is. With a key it must be https (or a local or private address), so
 *  the key never travels in cleartext. */
export function endpointUrlProblem(raw: string, withKey: boolean): string {
  let url: URL;
  try { url = new URL(raw.trim()); } catch { return "Enter a full URL such as https://llm.example.com/v1."; }
  if (url.protocol !== "https:" && url.protocol !== "http:") return "Use an http:// or https:// URL.";
  if (url.username || url.password || url.search || url.hash) return "Leave credentials, query and fragment out of the URL; the key has its own field.";
  if (withKey && url.protocol === "http:" && !privateHost(url.hostname)) return "A key is only sent over https://; change the URL to https.";
  return "";
}

function privateHost(host: string): boolean {
  const bare = host.replace(/^\[|\]$/g, "");
  if (bare === "localhost" || bare.endsWith(".localhost") || bare === "::1") return true;
  const octets = bare.split(".").map(Number);
  if (octets.length !== 4 || octets.some((o) => !Number.isInteger(o) || o < 0 || o > 255)) return false;
  const [a, b] = octets as [number, number, number, number];
  return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254);
}

/** What to tell the user when the endpoint's model list failed. Browsers hide the cause of a blocked request, so in
 *  browser mode a network failure is almost always CORS or an http URL on an https page. */
export function endpointHint(error: string, mode: string): string {
  if (mode !== "browser" || !/failed to fetch|networkerror|load failed|connection error|jsexception/i.test(error)) return "";
  return "The browser could not reach it. The endpoint must use https and allow this page's origin (CORS), e.g. vLLM: "
    + `--allowed-origins '["${typeof location === "undefined" ? "<this page>" : location.origin}"]'.`;
}

/** Group label of a catalog entry: the endpoint name for named endpoints, else the provider. */
export function groupOf(item: CatalogItem): string {
  return item.endpoint ?? item.source;
}
