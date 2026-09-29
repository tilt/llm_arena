// Shared list of runs, kept fresh: every few seconds while something runs, rarely otherwise, and not at all
// while the tab is hidden. The navigation badge and the Runs page read it.
import { app } from "./app.svelte";
import type { RunListing } from "./contracts";

export const runs = $state({ list: null as RunListing[] | null, error: "" });

const FAST_MS = 3000;
const SLOW_MS = 20000;
let timer: ReturnType<typeof setTimeout> | null = null;

export const activeRuns = () => (runs.list ?? []).filter((r) => r.active);

export async function refreshRuns(): Promise<void> {
  if (!app.backend) return;
  try {
    runs.list = await app.backend.runs();
    runs.error = "";
  } catch (error) {
    runs.error = error instanceof Error ? error.message : String(error);
  }
}

/** Start polling (idempotent). Call refreshRuns() after starting a run to show it at once. */
export function watchRuns(): () => void {
  const tick = async () => {
    if (document.visibilityState === "visible") await refreshRuns();
    timer = setTimeout(tick, activeRuns().length ? FAST_MS : SLOW_MS);
  };
  const wake = () => {
    if (document.visibilityState !== "visible") return;
    if (timer) clearTimeout(timer);
    void tick();
  };
  if (!timer) void tick();
  document.addEventListener("visibilitychange", wake);
  return () => {
    if (timer) clearTimeout(timer);
    timer = null;
    document.removeEventListener("visibilitychange", wake);
  };
}

/** "3 min ago" style, with the exact time available as a tooltip by the caller. */
export function ago(timestamp: string | number | null | undefined, now = Date.now()): string {
  if (timestamp === null || timestamp === undefined || timestamp === "") return "";
  const ms = typeof timestamp === "number" ? timestamp * 1000 : Date.parse(timestamp.replace(" ", "T"));
  if (Number.isNaN(ms)) return String(timestamp);
  const seconds = Math.max(0, Math.round((now - ms) / 1000));
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days < 30 ? `${days} d ago` : new Date(ms).toLocaleDateString();
}

export function elapsed(startedAt: number | null | undefined, now = Date.now()): string {
  if (!startedAt) return "";
  const seconds = Math.max(0, Math.round(now / 1000 - startedAt));
  const m = Math.floor(seconds / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : m ? `${m} min ${seconds % 60} s` : `${seconds} s`;
}
