/// <reference lib="webworker" />
// The browser engine: the Python arena (same code as the CLI) in Pyodide. Model calls go straight
// from here to the provider with the user's key; model-written code runs in a separate sandbox worker.
import type { EngineReply, EngineRequest } from "./protocol";
import { loadPyodide } from "./pyodide";

type Arena = Record<string, (...args: unknown[]) => unknown>;
let arena: Arena | null = null;
const post = (reply: EngineReply) => self.postMessage(reply);

// ---- sandbox worker (terminated and replaced on timeout) ----------------------------------
let sandbox: Worker | null = null;
let sandboxReady: Promise<unknown> | null = null;

function ask(worker: Worker, message: unknown, timeoutMs: number): Promise<{ timedOut: true } | { value: unknown }> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve({ timedOut: true }), timeoutMs);
    worker.onmessage = (event: MessageEvent) => { clearTimeout(timer); resolve({ value: event.data }); };
    worker.postMessage(message);
  });
}

async function sandboxRun(code: string, files: string, collect: string, timeoutS: number): Promise<string> {
  if (!sandbox) {
    sandbox = new Worker(new URL("./sandbox.worker.ts", import.meta.url), { type: "module" });
    sandboxReady = ask(sandbox, { cmd: "init" }, 180_000);
  }
  await sandboxReady;
  const started = performance.now();
  const reply = await ask(sandbox, { cmd: "exec", code, files, collect }, timeoutS * 1000);
  if ("timedOut" in reply) {
    sandbox.terminate(); // the only reliable way to stop runaway code in a worker
    sandbox = null;
    return JSON.stringify({ stdout: "", stderr: "", returncode: -1, timed_out: true, files: {}, duration_s: timeoutS });
  }
  const result = JSON.parse(reply.value as string) as Record<string, unknown>;
  return JSON.stringify({ ...result, duration_s: (performance.now() - started) / 1000 });
}

// ---- engine ----------------------------------------------------------------------------
async function init(wheelUrl: string): Promise<void> {
  post({ kind: "status", message: "Loading Python (first visit downloads ~10 MB)…" });
  const py = await loadPyodide();
  await py.loadPackage(["micropip", "pydantic", "pyyaml"]);
  post({ kind: "status", message: "Installing the arena engine…" });
  await py.pyimport("micropip").install!.callKwargs(wheelUrl, { deps: false });
  py.globals.set("emit", (raw: string) => post({ kind: "event", raw }));
  py.globals.set("sandbox_run", sandboxRun);
  arena = (await py.runPythonAsync(
    "from llm_arena.adapters.browser.bootstrap import create_arena\ncreate_arena(emit, sandbox_run)",
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
