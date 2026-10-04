/// <reference lib="webworker" />
// The browser engine: the Python arena (same code as the CLI) in Pyodide. Model calls go straight
// from here to the provider with the user's key; model-written code runs in a separate sandbox worker.
import type { EngineReply, EngineRequest } from "./protocol";
import { loadPyodide } from "./pyodide";
import { SandboxPool } from "./sandbox-pool";

type Arena = Record<string, (...args: unknown[]) => unknown>;
let arena: Arena | null = null;
const post = (reply: EngineReply) => self.postMessage(reply);

// One ready spare keeps normal execution fast; every worker is destroyed after its first run.
const sandboxPool = new SandboxPool(
  () => new Worker(new URL("./sandbox.worker.ts", import.meta.url), { type: "module" }),
);

async function sandboxRun(code: string, files: string, collect: string, timeoutS: number): Promise<string> {
  const started = performance.now();
  try {
    const reply = await sandboxPool.run(code, files, collect, timeoutS * 1000);
    const result = JSON.parse(reply.result) as Record<string, unknown>;
    return JSON.stringify({ ...result, duration_s: (performance.now() - started) / 1000,
      sandbox_init_s: reply.initMs / 1000, sandbox_acquire_s: reply.acquireMs / 1000,
      browser_network: reply.networkIsolation });
  } catch (error) {
    if (!(error instanceof DOMException && error.name === "AbortError")
        && !(error instanceof Error && error.message === "sandbox execution timed out")) throw error;
    return JSON.stringify({ stdout: "", stderr: "", returncode: -1, timed_out: true, files: {}, duration_s: timeoutS });
  }
}

// ---- engine ----------------------------------------------------------------------------
async function init(wheelUrl: string): Promise<void> {
  post({ kind: "status", message: "Loading Python (first visit downloads ~10 MB)…" });
  const py = await loadPyodide();
  await py.loadPackage(["micropip", "pydantic", "pyyaml"]);
  const browserNetwork = await sandboxPool.prewarm();
  post({ kind: "status", message: "Installing the arena engine…" });
  await py.pyimport("micropip").install!.callKwargs(wheelUrl, { deps: false });
  py.globals.set("emit", (raw: string) => post({ kind: "event", raw }));
  py.globals.set("sandbox_run", sandboxRun);
  arena = (await py.runPythonAsync(
    `from llm_arena.adapters.browser.bootstrap import create_arena\ncreate_arena(emit, sandbox_run, ${JSON.stringify(browserNetwork)})`,
  )) as Arena;
}

self.onmessage = async ({ data }: MessageEvent<EngineRequest>) => {
  const { id, method, args } = data;
  try {
    if (method === "init") {
      await init(args[0] as string);
      post({ kind: "result", id, result: null });
      return;
    }
    if (!arena) throw new Error("engine not initialised");
    const result = await arena[method]!(...args);
    post({ kind: "result", id, result: result ?? null });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    // Python exceptions arrive with a traceback; the last line carries the message.
    post({ kind: "error", id, error: message.trim().split("\n").at(-1) ?? message });
  }
};
