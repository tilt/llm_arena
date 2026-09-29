// The one seam between the UI and an arena engine. Views only ever use ArenaBackend, so the local
// app (HttpBackend) and the in-browser engine (WorkerBackend, Pyodide) are interchangeable.
import type {
  ModelPreset,
  CatalogEntry,
  Estimate,
  Leaderboard,
  ExperimentConfig,
  ModelSpec,
  RunBundle,
  RunEvent,
  RunListing,
  RenameRun,
  RuntimeResponse,
  ScenarioManifest,
  StartRun,
  TaskView,
  Trace,
} from "./contracts";

/** Where a run's traces and artifacts live, so the UI can say whether they survive this session. */
export type Persistence = "server" | "browser" | "session";

/** One trial's trace as stored (spans plus the trial record and scores). */
export interface TrialTrace extends Trace {
  trial?: Record<string, unknown>;
  scores?: Record<string, unknown>[];
}

export type CatalogItem = CatalogEntry & { ref: string };

export interface ModelsResponse {
  models: CatalogItem[];
  aliases: Record<string, ModelSpec>;
  unavailable: Record<string, string>;
}

export interface ArenaBackend {
  /** "local": FastAPI server with local models; "browser": engine in this tab, remote models only. */
  readonly kind: "local" | "browser";
  runtime(): Promise<RuntimeResponse>;
  scenarios(): Promise<ScenarioManifest[]>;
  models(refresh?: boolean): Promise<ModelsResponse>;
  /** remember: keep the key on this device (browser mode only; the local app keeps keys server-side). */
  setKey(provider: string, key: string, remember?: boolean): Promise<void>;
  clearKey(provider: string): Promise<void>;
  estimate(experiment: ExperimentConfig): Promise<Estimate>;
  startRun(request: StartRun): Promise<string>;
  /** Subscribe to a run's events (history first, then live). Returns an unsubscribe function. */
  events(runId: string, onEvent: (event: RunEvent) => void): () => void;
  cancel(runId: string): Promise<void>;
  /** New display name and setup names for a finished run; ids, links and results stay. */
  renameRun(runId: string, request: RenameRun): Promise<void>;
  runs(): Promise<RunListing[]>;
  bundle(runId: string): Promise<RunBundle>;
  /** Model presets: one model per kind of step. */
  presets(): Promise<Record<string, ModelPreset>>;
  /** Save a profile (null: back to the shipped version, or removed if it is your own). */
  savePreset(name: string, profile: ModelPreset | null): Promise<Record<string, ModelPreset>>;
  /** A scenario's tasks with their expected outcomes (benchmarks may download their subset first). */
  tasks(scenario: string): Promise<TaskView[]>;
  /** One trial's trace, loaded on demand. */
  trace(runId: string, trialId: string): Promise<TrialTrace | null>;
  /** A URL for an artifact (image, JSON, …) of a run, or null when it was not stored. */
  artifactUrl(runId: string, key: string): Promise<string | null>;
  /** Download URL for the full run bundle (with traces and artifacts), where the backend serves one. */
  exportUrl(runId: string): string | null;
  persistence(runId: string): Promise<Persistence>;
  /** Per-scenario leaderboards pooled over all runs this backend knows (comparable trials only). */
  leaderboard(): Promise<Leaderboard[]>;
  /** Static HTML report, where the backend can render one (local app only). */
  reportUrl(runId: string): string | null;
}

export class BackendError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

const EVENT_TYPES = ["run_started", "trial_started", "trial_finished", "budget_exceeded", "run_finished"] as const;

export class HttpBackend implements ArenaBackend {
  readonly kind = "local" as const;

  constructor(private readonly base = "") {}

  runtime(): Promise<RuntimeResponse> {
    return this.request("GET", "/api/runtime");
  }

  scenarios(): Promise<ScenarioManifest[]> {
    return this.request("GET", "/api/scenarios");
  }

  models(refresh = false): Promise<ModelsResponse> {
    return this.request("GET", `/api/models${refresh ? "?refresh=true" : ""}`);
  }

  setKey(provider: string, key: string): Promise<void> {
    return this.request("PUT", `/api/keys/${encodeURIComponent(provider)}`, { key });
  }

  clearKey(provider: string): Promise<void> {
    return this.request("DELETE", `/api/keys/${encodeURIComponent(provider)}`);
  }

  estimate(experiment: ExperimentConfig): Promise<Estimate> {
    return this.request("POST", "/api/estimate", experiment);
  }

  async startRun(request: StartRun): Promise<string> {
    const response = await this.request<{ run_id: string }>("POST", "/api/runs", request);
    return response.run_id;
  }

  events(runId: string, onEvent: (event: RunEvent) => void): () => void {
    const source = new EventSource(`${this.base}/api/runs/${encodeURIComponent(runId)}/events`);
    // The server names each SSE event by its type; onmessage would only see unnamed events.
    for (const type of EVENT_TYPES) {
      source.addEventListener(type, (message) => {
        const event = JSON.parse((message as MessageEvent<string>).data) as RunEvent;
        onEvent(event);
        if (event.type === "run_finished") source.close();
      });
    }
    return () => source.close();
  }

  cancel(runId: string): Promise<void> {
    return this.request("POST", `/api/runs/${encodeURIComponent(runId)}/cancel`);
  }

  renameRun(runId: string, request: RenameRun): Promise<void> {
    return this.request("PATCH", `/api/runs/${encodeURIComponent(runId)}`, request);
  }

  runs(): Promise<RunListing[]> {
    return this.request("GET", "/api/runs");
  }

  bundle(runId: string): Promise<RunBundle> {
    // Light bundle: traces load per trial when inspected.
    return this.request("GET", `/api/runs/${encodeURIComponent(runId)}/bundle?traces=false`);
  }

  tasks(scenario: string): Promise<TaskView[]> {
    return this.request("GET", `/api/scenarios/${encodeURIComponent(scenario)}/tasks`);
  }

  presets(): Promise<Record<string, ModelPreset>> {
    return this.request("GET", "/api/presets");
  }

  savePreset(name: string, profile: ModelPreset | null): Promise<Record<string, ModelPreset>> {
    const path = `/api/presets/${encodeURIComponent(name)}`;
    return profile ? this.request("PUT", path, profile) : this.request("DELETE", path);
  }

  async trace(runId: string, trialId: string): Promise<TrialTrace | null> {
    try {
      return await this.request("GET", `/api/runs/${encodeURIComponent(runId)}/trials/${encodeURIComponent(trialId)}/trace`);
    } catch (error) {
      if (error instanceof BackendError && error.status === 404) return null;
      throw error;
    }
  }

  async artifactUrl(runId: string, key: string): Promise<string | null> {
    return key ? `${this.base}/api/runs/${encodeURIComponent(runId)}/artifacts/${key.split("/").map(encodeURIComponent).join("/")}` : null;
  }

  exportUrl(runId: string): string {
    return `${this.base}/api/runs/${encodeURIComponent(runId)}/bundle?artifacts=true`;
  }

  async persistence(): Promise<Persistence> {
    return "server";
  }

  leaderboard(): Promise<Leaderboard[]> {
    return this.request("GET", "/api/leaderboard");
  }

  reportUrl(runId: string): string {
    return `${this.base}/api/runs/${encodeURIComponent(runId)}/report`;
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.base}${path}`, {
      method,
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const detail = await response.json().then((d: { detail?: unknown }) => d.detail).catch(() => response.statusText);
      // FastAPI's generic answers for routes it does not have: the page is newer than the running server.
      if (detail === "Method Not Allowed" || (detail === "Not Found" && path.startsWith("/api/"))) {
        throw new BackendError("The arena server is older than this page and does not know this action yet. Restart it"
          + " (stop make ui with Ctrl+C and start it again), then try again.", response.status);
      }
      throw new BackendError(typeof detail === "string" ? detail : JSON.stringify(detail), response.status);
    }
    return (response.status === 204 ? undefined : await response.json()) as T;
  }
}

/** Use the local app when this page is served by it; otherwise the caller falls back to browser mode. */
export async function detectLocalBackend(base = ""): Promise<HttpBackend | null> {
  try {
    const response = await fetch(`${base}/api/runtime`, { signal: AbortSignal.timeout(3000) });
    return response.ok ? new HttpBackend(base) : null;
  } catch {
    return null;
  }
}
