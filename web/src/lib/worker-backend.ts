// ArenaBackend for browser-only mode: the Python engine runs in a Pyodide worker in this tab.
// Keys live in the worker's memory (optionally remembered in localStorage on request); finished runs
// are kept in IndexedDB and can be exported/imported as RunBundle files.
import type { ArenaBackend, ModelsResponse, Persistence, TrialTrace } from "./backend";
import { BackendError } from "./backend";
import type {
  Candidate, CandidatesRequest, ClaimCheck, ClaimDraft, ClaimDraftRequest, ClaimExperimentRequest, ModelPreset, EndpointView, Estimate,
  RenameRun, ExperimentConfig, Leaderboard, ReproDraft, ReproDraftRequest, RunBundle, RunEvent, RunListing, RuntimeResponse, SaveEndpoint,
  ScenarioManifest, StartRun, TaskView, ThreadRequest, TrustStats,
} from "./contracts";
import type { EngineMethod, EngineReply } from "../engine/protocol";
import { editedPresets, storeEditedPresets, usablePresets } from "./presets";
import { listBundles, loadBundle, saveBundle } from "./idb";
import {
  enforceCredentialStorage, readRememberedEndpoints, readRememberedKeys, writeRememberedEndpoints, writeRememberedKeys,
} from "./credential-storage";

export interface SelftestResult { case: string; status: "pass" | "fail" | "skipped"; mismatches?: string[]; reason?: string }

export class WorkerBackend implements ArenaBackend {
  readonly kind = "browser" as const;
  readonly ready: Promise<void>;
  private readonly worker: Worker;
  private seq = 0;
  private readonly pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
  private readonly history = new Map<string, RunEvent[]>();
  private readonly listeners = new Map<string, Set<(e: RunEvent) => void>>();
  // Finished runs whose bundle could not be written to IndexedDB (private window, quota): kept for this session.
  private readonly unsaved = new Map<string, RunBundle>();
  private readonly blobUrls = new Map<string, string>();
  private readonly canRememberKeys: boolean;

  constructor(wheelUrl: string, onStatus: (message: string) => void = () => {}) {
    this.canRememberKeys = enforceCredentialStorage().canRemember;
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
    if (this.canRememberKeys) {
      const keys = readRememberedKeys();
      if (remember) keys[provider] = key; else delete keys[provider];
      writeRememberedKeys(keys);
    }
    await this.call("models", true);
  }

  async clearKey(provider: string): Promise<void> {
    await this.call("clear_key", provider);
    if (this.canRememberKeys) {
      const keys = readRememberedKeys();
      delete keys[provider];
      writeRememberedKeys(keys);
    }
    await this.call("models", true);
  }

  async endpoints(): Promise<EndpointView[]> { return this.json("endpoints"); }

  async saveEndpoint(id: string, endpoint: SaveEndpoint, remember = false): Promise<EndpointView> {
    const view = await this.json<EndpointView>("set_endpoint", id, JSON.stringify(endpoint));
    if (this.canRememberKeys) {
      const endpoints = readRememberedEndpoints();
      const before = endpoints[id];
      // Same rule as the engine: a key stays with the URL it was entered for.
      const key = endpoint.key || (before && before.base_url === endpoint.base_url ? before.key : undefined);
      // The salt keeps the restored endpoint's identity, so its runs keep pooling on the leaderboard.
      if (remember) endpoints[id] = { ...endpoint, key: key ?? null, salt: view.salt }; else delete endpoints[id];
      writeRememberedEndpoints(endpoints);
    }
    await this.call("models", true);
    return view;
  }

  async removeEndpoint(id: string): Promise<void> {
    await this.call("clear_endpoint", id);
    if (this.canRememberKeys) {
      const endpoints = readRememberedEndpoints();
      delete endpoints[id];
      writeRememberedEndpoints(endpoints);
    }
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
    const saved = this.unsaved.get(runId) ?? (await loadBundle(runId).catch(() => undefined));
    return saved ?? this.json("bundle", runId);
  }

  /** Pools the trials of every run saved in this browser; the engine applies the same rules as the local app. */
  async leaderboard(): Promise<Leaderboard[]> {
    const trials = (await listBundles()).flatMap((b) => b.trials.map((t) => ({ ...t, run_id: t.run_id ?? b.run.run_id })));
    return this.json("leaderboard", JSON.stringify(trials));
  }

  async tasks(scenario: string): Promise<TaskView[]> { return this.json("tasks", scenario); }

  /** Shipped presets from the engine, overlaid with the ones edited in this browser. */
  async presets(): Promise<Record<string, ModelPreset>> {
    // Only presets a web page can run: local models (Ollama, LM Studio) and Ollaya/Jev are out of reach here.
    return usablePresets({ ...(await this.json<Record<string, ModelPreset>>("presets")), ...editedPresets() }, true);
  }

  async savePreset(name: string, profile: ModelPreset | null): Promise<Record<string, ModelPreset>> {
    const edited = editedPresets();
    if (profile) edited[name] = profile; else delete edited[name];
    storeEditedPresets(edited);
    return this.presets();
  }

  async trace(runId: string, trialId: string): Promise<TrialTrace | null> {
    const bundle = await this.bundle(runId);
    return (bundle.traces?.[trialId] as TrialTrace | undefined) ?? null;
  }

  /** Artifacts travel inside the bundle (base64); each becomes a blob URL once and is reused. */
  async artifactUrl(runId: string, key: string): Promise<string | null> {
    const id = `${runId}|${key}`;
    if (this.blobUrls.has(id)) return this.blobUrls.get(id)!;
    const file = key ? (await this.bundle(runId)).artifacts?.[key] : undefined;
    if (!file) return null;
    const bytes = Uint8Array.from(atob(file.data), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: file.media_type }));
    this.blobUrls.set(id, url);
    return url;
  }

  exportUrl(): null { return null; }

  /** The engine renames runs of this tab in memory; the saved bundle (IndexedDB) gets the same names. */
  async renameRun(runId: string, request: RenameRun): Promise<void> {
    const bundle = await this.bundle(runId);
    const renamed = await this.json<RunBundle>("rename", runId, JSON.stringify(bundle), JSON.stringify(request));
    try {
      if (this.unsaved.has(runId)) throw new Error("not saved");
      await saveBundle(runId, renamed);
    } catch {
      this.unsaved.set(runId, renamed);
    }
  }

  async persistence(runId: string): Promise<Persistence> {
    return this.unsaved.has(runId) || !(await loadBundle(runId).catch(() => undefined)) ? "session" : "browser";
  }

  private async keep(runId: string): Promise<void> {
    const bundle = await this.json<RunBundle>("bundle", runId);
    try {
      await saveBundle(runId, bundle);
      this.unsaved.delete(runId);
    } catch {
      this.unsaved.set(runId, bundle);
    }
  }

  /** An imported run file: the engine validates it first, and an id already in use here gets a suffix
   *  (`<id>-imported-N`), so an import never overwrites a run of this browser. */
  async importBundle(file: File): Promise<string> {
    const checked = await this.json<RunBundle>("check_bundle", await file.text());
    const taken = new Set([...(await listBundles()).map((b) => String(b.run.run_id ?? "")), ...this.unsaved.keys()]);
    const runId = importId(String(checked.run.run_id), taken);
    const bundle = runId === checked.run.run_id ? checked : {
      ...checked, run: { ...checked.run, run_id: runId },
      trials: checked.trials.map((t) => ({ ...t, run_id: runId })),
    };
    await saveBundle(runId, bundle);
    return runId;
  }

  async claimCheck(claim: string): Promise<ClaimCheck> { return this.json("claim_check", claim); }
  async claimDraft(runId: string, request: ClaimDraftRequest): Promise<ClaimDraft> {
    return this.json("claim_draft", JSON.stringify(await this.bundle(runId)), JSON.stringify(request));
  }
  async reproDraft(runId: string, request: ReproDraftRequest): Promise<ReproDraft> {
    return this.json("repro_draft", JSON.stringify(await this.bundle(runId)), JSON.stringify(request));
  }
  async claimExperiment(request: ClaimExperimentRequest): Promise<ExperimentConfig> {
    return this.json("claim_experiment", JSON.stringify(request));
  }
  async claimCandidates(request: CandidatesRequest): Promise<Candidate[]> { return this.json("claim_candidates", JSON.stringify(request)); }
  async claimThread(request: ThreadRequest): Promise<TrustStats> { return this.json("claim_thread", JSON.stringify(request)); }

  async selftest(vectors: Record<string, unknown>): Promise<SelftestResult[]> {
    return this.json("selftest", JSON.stringify(vectors));
  }

  private async restoreKeys(): Promise<void> {
    if (!this.canRememberKeys) return;
    for (const [provider, key] of Object.entries(readRememberedKeys())) await this.call("set_key", provider, key);
    for (const [id, endpoint] of Object.entries(readRememberedEndpoints())) {
      await this.call("set_endpoint", id, JSON.stringify(endpoint)).catch(() => undefined);  // a stale entry is skipped
    }
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
      if (event.type === "run_finished") void this.keep(runId);
      return;
    }
    const pending = this.pending.get(reply.id);
    if (!pending) return;
    this.pending.delete(reply.id);
    if (reply.kind === "result") pending.resolve(reply.result);
    else pending.reject(new BackendError(reply.error, 400));
  }
}

/** The id an imported run gets: its own, or `<id>-imported-N` when that is already taken here. */
export function importId(runId: string, taken: Set<string>): string {
  if (!taken.has(runId)) return runId;
  let n = 1;
  while (taken.has(`${runId}-imported-${n}`)) n++;
  return `${runId}-imported-${n}`;
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
