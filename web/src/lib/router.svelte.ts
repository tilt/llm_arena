// Minimal hash router: works on GitHub Pages (no server rewrites) and in the local app alike.
export type Route =
  | { name: "home" }
  | { name: "models" }
  | { name: "build" }
  | { name: "runs" }
  | { name: "leaderboard" }
  | { name: "selftest" }
  | { name: "run"; id: string };

export function parse(hash: string): Route {
  const [, section, id] = hash.replace(/^#/, "").split("/");
  if (section === "models") return { name: "models" };
  if (section === "build") return { name: "build" };
  if (section === "runs" && id) return { name: "run", id: decodeURIComponent(id) };
  if (section === "runs") return { name: "runs" };
  if (section === "leaderboard") return { name: "leaderboard" };
  if (section === "selftest") return { name: "selftest" };
  return { name: "home" };
}

export const router = $state({ route: parse(location.hash) });
addEventListener("hashchange", () => (router.route = parse(location.hash)));

export function go(path: string): void {
  location.hash = path;
}
