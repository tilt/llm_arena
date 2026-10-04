// Pyodide code is never imported until the pinned bytes pass SHA-256 verification.
import { PYODIDE_BASE_URL, PYODIDE_CORE, SANDBOX_PACKAGES, SANDBOX_PACKAGE_NAMES,
  type VerifiedAsset } from "./pyodide-assets";

export interface PyProxyCallable {
  (...args: unknown[]): unknown;
  callKwargs(...args: unknown[]): unknown;
}

export interface Pyodide {
  loadPackage(names: string | string[]): Promise<void>;
  pyimport(name: string): Record<string, PyProxyCallable>;
  runPythonAsync(code: string): Promise<unknown>;
  globals: { set(name: string, value: unknown): void };
}

interface LoadOptions { sandbox?: boolean }
type ModuleFactory = (settings: Record<string, unknown>) => Promise<unknown>;
const VIRTUAL_BASE = "https://arena.invalid/verified-pyodide/";

export async function loadPyodide(options: LoadOptions = {}): Promise<Pyodide> {
  const assets = options.sandbox ? [...Object.values(PYODIDE_CORE), ...SANDBOX_PACKAGES]
    : Object.values(PYODIDE_CORE);
  const verified = new Map((await Promise.all(assets.map(async (asset) =>
    [asset.file, await fetchVerified(asset)] as const))));
  const moduleBytes = required(verified, PYODIDE_CORE.module!.file);
  const asmBytes = required(verified, PYODIDE_CORE.asm!.file);
  required(verified, PYODIDE_CORE.wasm!.file);
  const lockContents = new TextDecoder().decode(required(verified, PYODIDE_CORE.lock!.file));
  const originalFetch = globalThis.fetch.bind(globalThis);
  const virtualFetch = async (input: RequestInfo | URL): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const file = url.startsWith(VIRTUAL_BASE) ? url.slice(VIRTUAL_BASE.length) : "";
    const bytes = verified.get(file);
    if (bytes) {
      const type = file.endsWith(".wasm") ? "application/wasm" : "application/octet-stream";
      return new Response(bytes.slice(0), { status: 200, headers: { "Content-Type": type } });
    }
    if (!options.sandbox) return originalFetch(input);
    throw new TypeError("Network access is disabled in the browser sandbox");
  };
  globalThis.fetch = virtualFetch as typeof fetch;

  const moduleUrl = URL.createObjectURL(new Blob([moduleBytes], { type: "text/javascript" }));
  const asmUrl = URL.createObjectURL(new Blob([asmBytes], { type: "text/javascript" }));
  try {
    const [{ loadPyodide: load }, { default: createPyodideModule }] = await Promise.all([
      import(/* @vite-ignore */ moduleUrl) as Promise<{ loadPyodide(config: Record<string, unknown>): Promise<Pyodide> }>,
      import(/* @vite-ignore */ asmUrl) as Promise<{ default: ModuleFactory }>,
    ]);
    const pyodide = await load({
      indexURL: VIRTUAL_BASE,
      packageBaseUrl: options.sandbox ? VIRTUAL_BASE : PYODIDE_BASE_URL,
      stdLibURL: VIRTUAL_BASE + PYODIDE_CORE.stdlib!.file,
      lockFileContents: lockContents,
      createPyodideModule,
    });
    if (options.sandbox) {
      await pyodide.loadPackage([...SANDBOX_PACKAGE_NAMES]);
      denySandboxNetwork();
    }
    return pyodide;
  } finally {
    URL.revokeObjectURL(moduleUrl);
    URL.revokeObjectURL(asmUrl);
    if (!options.sandbox) globalThis.fetch = originalFetch as typeof fetch;
  }
}

export async function sha256(bytes: ArrayBuffer): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)))
    .map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function fetchVerified(asset: VerifiedAsset): Promise<ArrayBuffer> {
  const response = await fetch(PYODIDE_BASE_URL + asset.file, { cache: "force-cache", credentials: "omit" });
  if (!response.ok) throw new Error(`failed to fetch pinned Pyodide asset: ${asset.file}`);
  const bytes = await response.arrayBuffer();
  const actual = await sha256(bytes);
  if (actual !== asset.sha256) throw new Error(`Pyodide asset digest mismatch: ${asset.file}`);
  return bytes;
}

function required(assets: Map<string, ArrayBuffer>, file: string): ArrayBuffer {
  const bytes = assets.get(file);
  if (!bytes) throw new Error(`verified Pyodide asset missing: ${file}`);
  return bytes;
}

function denySandboxNetwork(): void {
  const denied = (): never => { throw new TypeError("Network access is disabled in the browser sandbox"); };
  for (const name of ["fetch", "WebSocket", "EventSource", "XMLHttpRequest", "Worker", "SharedWorker"]) {
    try { Object.defineProperty(globalThis, name, { value: denied, writable: false, configurable: false }); }
    catch { /* An absent browser API needs no replacement. */ }
  }
}
