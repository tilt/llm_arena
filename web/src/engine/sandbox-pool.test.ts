import { describe, expect, it } from "vitest";
import { SandboxPool, type WorkerLike } from "./sandbox-pool";
import type { SandboxRequest } from "./sandbox-protocol";

class FakeWorker extends EventTarget implements WorkerLike {
  terminated = false;
  private canary: string | undefined;

  constructor(private readonly harness: Harness) {
    super();
    harness.created += 1;
    harness.live += 1;
    harness.maxLive = Math.max(harness.maxLive, harness.live);
  }

  postMessage(value: unknown): void {
    const request = value as SandboxRequest;
    if (request.kind === "init") {
      queueMicrotask(() => this.reply({ kind: "ready", requestId: request.requestId, initMs: 12,
        networkIsolation: "not network-isolated" }));
      return;
    }
    if (request.code === "hold") {
      this.harness.held.push(() => this.result(request, "held"));
      return;
    }
    if (request.code === "stale") {
      this.reply({ kind: "result", requestId: "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa", result: '"wrong"' });
      queueMicrotask(() => this.result(request, "right"));
      return;
    }
    if (request.code === "malformed") {
      this.reply({ kind: "result", requestId: request.requestId, result: 42 });
      return;
    }
    if (request.code.startsWith("set:")) this.canary = request.code.slice(4);
    this.result(request, request.code === "get" ? (this.canary ?? "clean") : "ok");
  }

  terminate(): void {
    if (this.terminated) return;
    this.terminated = true;
    this.harness.terminated += 1;
    this.harness.live -= 1;
  }

  private result(request: Extract<SandboxRequest, { kind: "execute" }>, result: string): void {
    queueMicrotask(() => this.reply({ kind: "result", requestId: request.requestId, result: JSON.stringify(result) }));
  }

  private reply(data: unknown): void {
    if (!this.terminated) this.dispatchEvent(new MessageEvent("message", { data }));
  }
}

class Harness {
  created = 0;
  live = 0;
  maxLive = 0;
  terminated = 0;
  held: Array<() => void> = [];
  factory = (): FakeWorker => new FakeWorker(this);
}

describe("SandboxPool", () => {
  it("routes by request ID and ignores a stale response", async () => {
    const harness = new Harness();
    const pool = new SandboxPool(harness.factory);
    await pool.prewarm();
    const reply = await pool.run("stale", "{}", "[]", 1000);
    expect(JSON.parse(reply.result)).toBe("right");
    expect(reply.initMs).toBe(12);
    expect(harness.terminated).toBe(1);
  });

  it("terminates a worker on a schema violation", async () => {
    const harness = new Harness();
    const pool = new SandboxPool(harness.factory);
    await expect(pool.run("malformed", "{}", "[]", 1000)).rejects.toThrow("invalid or oversized sandbox result");
    expect(harness.terminated).toBe(1);
  });

  it("terminates an active worker when cancelled", async () => {
    const harness = new Harness();
    const pool = new SandboxPool(harness.factory);
    const controller = new AbortController();
    const run = pool.run("hold", "{}", "[]", 1000, controller.signal);
    await until(() => harness.held.length === 1);
    controller.abort();
    await expect(run).rejects.toMatchObject({ name: "AbortError" });
    expect(harness.terminated).toBe(1);
  });

  it("runs at most two executions and owns at most three workers", async () => {
    const harness = new Harness();
    const pool = new SandboxPool(harness.factory);
    await pool.prewarm();
    const runs = [pool.run("hold", "{}", "[]", 1000), pool.run("hold", "{}", "[]", 1000),
      pool.run("hold", "{}", "[]", 1000)];
    await until(() => harness.held.length === 2 && pool.stats().queued === 1);
    expect(pool.stats().active).toBe(2);
    expect(harness.maxLive).toBeLessThanOrEqual(3);
    harness.held.shift()!();
    await until(() => harness.held.length === 2);
    harness.held.shift()!();
    harness.held.shift()!();
    await Promise.all(runs);
    expect(harness.maxLive).toBeLessThanOrEqual(3);
    expect(pool.stats().active).toBe(0);
  });

  it("does not preserve execution state in the next worker", async () => {
    const harness = new Harness();
    const pool = new SandboxPool(harness.factory);
    await pool.run("set:secret-canary", "{}", "[]", 1000);
    const second = await pool.run("get", "{}", "[]", 1000);
    expect(JSON.parse(second.result)).toBe("clean");
    expect(harness.terminated).toBe(2);
  });
});

async function until(predicate: () => boolean): Promise<void> {
  for (let index = 0; index < 100; index += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 1));
  }
  throw new Error("condition was not reached");
}
