// The one seam between the UI and an arena engine. Views only ever use ArenaBackend, so the local
// app (HttpBackend) and the in-browser engine (WorkerBackend, Pyodide) are interchangeable.
import type {
  CatalogEntry,
  Estimate,
  ExperimentConfig,
  ModelSpec,
  RunBundle,
  RunEvent,
  RunListing,
  RuntimeResponse,
  ScenarioManifest,
  StartRun,
} from "./contracts";

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
  setKey(provider: string, key: string): Promise<void>;
  clearKey(provider: string): Promise<void>;
  estimate(experiment: ExperimentConfig): Promise<Estimate>;
  startRun(request: StartRun): Promise<string>;
  /** Subscribe to a run's events (history first, then live). Returns an unsubscribe function. */
  events(runId: string, onEvent: (event: RunEvent) => void): () => void;
  cancel(runId: string): Promise<void>;
  runs(): Promise<RunListing[]>;
  bundle(runId: string): Promise<RunBundle>;
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

  runs(): Promise<RunListing[]> {
    return this.request("GET", "/api/runs");
  }

  bundle(runId: string): Promise<RunBundle> {
    return this.request("GET", `/api/runs/${encodeURIComponent(runId)}/bundle`);
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
