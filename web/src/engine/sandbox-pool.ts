import { requestId, type SandboxReply, type SandboxRequest, validateSandboxReply } from "./sandbox-protocol";

const INIT_TIMEOUT_MS = 180_000;
const MAX_EXECUTIONS = 2;
const MAX_WORKERS = 3;

export interface WorkerLike extends EventTarget {
  postMessage(message: unknown): void;
  terminate(): void;
}

interface ReadyWorker {
  worker: WorkerLike;
  initMs: number;
  networkIsolation: "isolated" | "not network-isolated";
}

interface Queued {
  resolve: () => void;
  reject: (error: Error) => void;
  signal?: AbortSignal;
  abort?: () => void;
}

export interface SandboxRunResult {
  result: string;
  acquireMs: number;
  initMs: number;
  networkIsolation: "isolated" | "not network-isolated";
}

export class SandboxPool {
  private active = 0;
  private total = 0;
  private spare: Promise<ReadyWorker> | undefined;
  private readonly queue: Queued[] = [];

  constructor(private readonly createWorker: () => WorkerLike) {}

  async prewarm(): Promise<"isolated" | "not network-isolated"> {
    return (await this.ensureSpare()).networkIsolation;
  }

  async run(code: string, files: string, collect: string, timeoutMs: number,
    signal?: AbortSignal): Promise<SandboxRunResult> {
    const acquireStarted = performance.now();
    await this.reserve(signal);
    let ready: ReadyWorker | undefined;
    try {
      ready = await this.acquire(signal);
      const acquireMs = performance.now() - acquireStarted;
      const reply = await exchange(ready.worker, { kind: "execute", requestId: requestId(), code, files, collect },
        "result", timeoutMs, signal);
      if (reply.kind === "error") throw new Error(reply.error);
      if (reply.kind !== "result") throw new Error("sandbox returned the wrong response type");
      return { result: reply.result, acquireMs, initMs: ready.initMs,
        networkIsolation: ready.networkIsolation };
    } finally {
      if (ready) this.destroy(ready.worker);
      this.active -= 1;
      this.releaseNext();
      void this.ensureSpare().catch(() => undefined);
    }
  }

  stats(): { active: number; total: number; queued: number; spare: boolean } {
    return { active: this.active, total: this.total, queued: this.queue.length, spare: this.spare !== undefined };
  }

  private async reserve(signal?: AbortSignal): Promise<void> {
    if (signal?.aborted) throw abortError();
    if (this.active < MAX_EXECUTIONS) {
      this.active += 1;
      return;
    }
    await new Promise<void>((resolve, reject) => {
      const item: Queued = { resolve, reject, signal };
      item.abort = () => {
        const index = this.queue.indexOf(item);
        if (index >= 0) this.queue.splice(index, 1);
        reject(abortError());
      };
      signal?.addEventListener("abort", item.abort, { once: true });
      this.queue.push(item);
    });
  }

  private releaseNext(): void {
    while (this.queue.length) {
      const item = this.queue.shift()!;
      item.signal?.removeEventListener("abort", item.abort!);
      if (item.signal?.aborted) continue;
      this.active += 1;
      item.resolve();
      return;
    }
  }

  private async acquire(signal?: AbortSignal): Promise<ReadyWorker> {
    const candidate = this.spare;
    this.spare = undefined;
    const ready = candidate ? await candidate : await this.createReady();
    if (signal?.aborted) {
      this.destroy(ready.worker);
      throw abortError();
    }
    void this.ensureSpare().catch(() => undefined);
    return ready;
  }

  private ensureSpare(): Promise<ReadyWorker> {
    if (!this.spare) {
      if (this.total >= MAX_WORKERS) return Promise.reject(new Error("sandbox worker limit reached"));
      this.spare = this.createReady();
    }
    return this.spare;
  }

  private async createReady(): Promise<ReadyWorker> {
    this.total += 1;
    const worker = this.createWorker();
    const id = requestId();
    try {
      const reply = await exchange(worker, { kind: "init", requestId: id }, "ready", INIT_TIMEOUT_MS);
      if (reply.kind === "error") throw new Error(reply.error);
      if (reply.kind !== "ready") throw new Error("sandbox did not become ready");
      return { worker, initMs: reply.initMs, networkIsolation: reply.networkIsolation };
    } catch (error) {
      this.destroy(worker);
      throw error;
    }
  }

  private destroy(worker: WorkerLike): void {
    worker.terminate();
    this.total = Math.max(0, this.total - 1);
  }
}

function exchange(worker: WorkerLike, request: SandboxRequest, expected: "ready" | "result", timeoutMs: number,
  signal?: AbortSignal): Promise<SandboxReply> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (action: () => void): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      worker.removeEventListener("message", onMessage);
      worker.removeEventListener("error", onError);
      worker.removeEventListener("messageerror", onMessageError);
      signal?.removeEventListener("abort", onAbort);
      action();
    };
    const onMessage = (event: Event): void => {
      const message = event as MessageEvent<unknown>;
      if (message.target !== null && message.target !== worker) return finish(() => reject(new Error("invalid sandbox message source")));
      let reply: SandboxReply;
      try { reply = validateSandboxReply(message.data); }
      catch (error) { return finish(() => reject(asError(error))); }
      if (reply.requestId !== request.requestId) return; // a late response may not satisfy another request
      if (reply.kind !== expected && reply.kind !== "error") {
        return finish(() => reject(new Error("unexpected sandbox response type")));
      }
      finish(() => resolve(reply));
    };
    const onError = (): void => finish(() => reject(new Error("sandbox worker failed")));
    const onMessageError = (): void => finish(() => reject(new Error("sandbox response could not be decoded")));
    const onAbort = (): void => finish(() => reject(abortError()));
    const timer = setTimeout(() => finish(() => reject(new Error("sandbox execution timed out"))), timeoutMs);
    worker.addEventListener("message", onMessage);
    worker.addEventListener("error", onError);
    worker.addEventListener("messageerror", onMessageError);
    signal?.addEventListener("abort", onAbort, { once: true });
    worker.postMessage(request);
  });
}

function abortError(): Error {
  return new DOMException("Sandbox execution cancelled", "AbortError");
}

function asError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}
