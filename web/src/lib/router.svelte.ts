// Minimal hash router: works on GitHub Pages (no server rewrites) and in the local app alike.
export type Route =
  | { name: "home" }
  | { name: "models" }
  | { name: "build" }
  | { name: "runs" }
  | { name: "leaderboard"; scenario?: string; entry?: string }
  | { name: "presets" }
  | { name: "scenario"; id: string; tab?: string }
  | { name: "selftest" }
  | { name: "run"; id: string; trial?: string; step?: string };

export function parse(hash: string): Route {
  const [, section, id, sub, subId, detail, detailId] = hash.replace(/^#/, "").split("/");
  if (section === "models") return { name: "models" };
  if (section === "build") return { name: "build" };
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

export const router = $state({ route: parse(location.hash) });
addEventListener("hashchange", () => (router.route = parse(location.hash)));

export function go(path: string): void {
  location.hash = path;
}
