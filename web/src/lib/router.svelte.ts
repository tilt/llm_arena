// Minimal hash router: works on GitHub Pages (no server rewrites) and in the local app alike.
import { parseClaimHash, type ClaimLink } from "./claims";

export type Route =
  | { name: "home" }
  | { name: "models" }
  | { name: "experiments"; template?: string }
  | { name: "runs" }
  | { name: "leaderboard"; scenario?: string; entry?: string }
  | { name: "presets" }
  | { name: "scenario"; id: string; tab?: string }
  | { name: "selftest" }
  | { name: "run"; id: string; trial?: string; step?: string }
  | { name: "claim"; link: ClaimLink | null };

export function parse(hash: string): Route {
  const path = hash.replace(/^#/, "");
  // A claim link's rest is opaque (gist/<id>@<revision>, or base64url of the claim), so it is not split on "/".
  if (path.startsWith("/claim/")) return { name: "claim", link: parseClaimHash(path.slice("/claim/".length)) };
  const [, section, id, sub, subId, detail, detailId] = path.split("/");
  if (section === "models") return { name: "models" };
  if (section === "experiments" || section === "build") return { name: "experiments", template: id ? decodeURIComponent(id) : undefined };
  if (section === "runs" && id) {
    const trial = sub === "trial" && subId ? decodeURIComponent(subId) : undefined;
    const step = trial && detail === "step" && detailId ? decodeURIComponent(detailId) : undefined;
    return { name: "run", id: decodeURIComponent(id), trial, step };
  }
  if (section === "runs") return { name: "runs" };
  if (section === "leaderboard") {
    return { name: "leaderboard", scenario: id ? decodeURIComponent(id) : undefined, entry: sub ? decodeURIComponent(sub) : undefined };
  }
  if (section === "presets" || section === "settings") return { name: "presets" }; // #/settings: old links
  if (section === "scenarios" && id) return { name: "scenario", id: decodeURIComponent(id), tab: sub };
  if (section === "selftest") return { name: "selftest" };
  return { name: "home" };
}

const currentHash = () => (typeof location === "undefined" ? "" : location.hash);

export const router = $state({ route: parse(currentHash()) });
if (typeof addEventListener !== "undefined") addEventListener("hashchange", () => (router.route = parse(currentHash())));

export function go(path: string): void {
  location.hash = path;
}

/** Change the address without a history entry (replaceState fires no hashchange, so the route is set here). */
export function replace(path: string): void {
  history.replaceState(history.state, "", `#${path}`);
  router.route = parse(currentHash());
}
