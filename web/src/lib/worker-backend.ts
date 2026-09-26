// ArenaBackend for browser-only mode: the Python engine runs in a Pyodide worker in this tab.
// Keys live in the worker's memory (optionally remembered in localStorage on request); finished runs
// are kept in IndexedDB and can be exported/imported as RunBundle files.
import type { ArenaBackend, ModelsResponse } from "./backend";
import { BackendError } from "./backend";
import type {
  Estimate, ExperimentConfig, RunBundle, RunEvent, RunListing, RuntimeResponse, ScenarioManifest, StartRun,
} from "./contracts";
import type { EngineMethod, EngineReply } from "../engine/protocol";
import { listBundles, loadBundle, saveBundle } from "./idb";

const REMEMBERED = "llm-arena.keys";

export interface SelftestResult { case: string; status: "pass" | "fail" | "skipped"; mismatches?: string[]; reason?: string }

export class WorkerBackend implements ArenaBackend {
  readonly kind = "browser" as const;
  readonly ready: Promise<void>;
  private readonly worker: Worker;
  private seq = 0;
  private readonly pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
  private readonly history = new Map<string, RunEvent[]>();
  private readonly listeners = new Map<string, Set<(e: RunEvent) => void>>();

  constructor(wheelUrl: string, onStatus: (message: string) => void = () => {}) {
    this.worker = new Worker(new URL("../engine/engine.worker.ts", import.meta.url), { type: "module" });
    this.worker.onmessage = ({ data }: MessageEvent<EngineReply>) => this.receive(data, onStatus);
    this.ready = this.call("init", wheelUrl).then(() => this.restoreKeys());
  }

  async runtime(): Promise<RuntimeResponse> { return this.json("runtime"); }
  async scenarios(): Promise<ScenarioManifest[]> { return this.json("scenarios"); }
  async models(refresh = false): Promise<ModelsResponse> { return this.json("models", refresh); }
  async estimate(experiment: ExperimentConfig): Promise<Estimate> { return this.json("estimate", JSON.stringify(experiment)); }
  async startRun(request: StartRun): Promise<string> { return (await this.call("start_run", JSON.stringify(request))) as string; }
  async cancel(runId: string): Promise<void> { await this.call("cancel", runId); }
  reportUrl(): null { return null; }

  async setKey(provider: string, key: string, remember = false): Promise<void> {
    await this.call("set_key", provider, key);
    const keys = this.remembered();
    if (remember) keys[provider] = key; else delete keys[provider];
    localStorage.setItem(REMEMBERED, JSON.stringify(keys));
    await this.call("models", true);
  }

  async clearKey(provider: string): Promise<void> {
    await this.call("clear_key", provider);
    const keys = this.remembered();
    delete keys[provider];
    localStorage.setItem(REMEMBERED, JSON.stringify(keys));
    await this.call("models", true);
  }

  events(runId: string, onEvent: (event: RunEvent) => void): () => void {
    for (const event of this.history.get(runId) ?? []) onEvent(event);
    const set = this.listeners.get(runId) ?? new Set();
    set.add(onEvent);
    this.listeners.set(runId, set);
    return () => set.delete(onEvent);
  }

  async runs(): Promise<RunListing[]> {
    const live = await this.json<RunListing[]>("runs");
    const saved = (await listBundles()).map((b) => listingOf(b)).filter((s) => !live.some((l) => l.run_id === s.run_id));
    return [...live, ...saved].sort((a, b) => b.run_id.localeCompare(a.run_id));
  }

  async bundle(runId: string): Promise<RunBundle> {
    const saved = await loadBundle(runId);
    return saved ?? this.json("bundle", runId);
  }

  async importBundle(file: File): Promise<string> {
    const bundle = JSON.parse(await file.text()) as RunBundle;
    const runId = String(bundle.run.run_id ?? file.name.replace(/\.json$/, ""));
    await saveBundle(runId, bundle);
    return runId;
  }

  async selftest(vectors: Record<string, unknown>): Promise<SelftestResult[]> {
    return this.json("selftest", JSON.stringify(vectors));
  }

  private remembered(): Record<string, string> {
    try {
      return JSON.parse(localStorage.getItem(REMEMBERED) ?? "{}") as Record<string, string>;
    } catch {
      return {};
    }
  }

  private async restoreKeys(): Promise<void> {
    for (const [provider, key] of Object.entries(this.remembered())) await this.call("set_key", provider, key);
  }

  private async json<T>(method: EngineMethod, ...args: unknown[]): Promise<T> {
    return JSON.parse((await this.call(method, ...args)) as string) as T;
  }

  private call(method: EngineMethod, ...args: unknown[]): Promise<unknown> {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ id, method, args });
    });
  }

  private receive(reply: EngineReply, onStatus: (message: string) => void): void {
    if (reply.kind === "status") return onStatus(reply.message);
    if (reply.kind === "event") {
      const { run_id: runId, event } = JSON.parse(reply.raw) as { run_id: string; event: RunEvent };
      this.history.set(runId, [...(this.history.get(runId) ?? []), event]);
      for (const listener of this.listeners.get(runId) ?? []) listener(event);
      if (event.type === "run_finished") void this.json<RunBundle>("bundle", runId).then((b) => saveBundle(runId, b));
      return;
    }
    const pending = this.pending.get(reply.id);
    if (!pending) return;
    this.pending.delete(reply.id);
    if (reply.kind === "result") pending.resolve(reply.result);
    else pending.reject(new BackendError(reply.error, 400));
  }
}

function listingOf(bundle: RunBundle): RunListing {
  return {
    run_id: String(bundle.run.run_id ?? ""),
    name: String(bundle.run.name ?? ""),
    created_at: String(bundle.run.created_at ?? ""),
    trials: bundle.trials.length,
    passed: bundle.trials.filter((t) => t.passed).length,
    errors: bundle.trials.filter((t) => t.status !== "ok").length,
    active: false,
  };
}
