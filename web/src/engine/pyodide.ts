// Pyodide is loaded from its CDN at runtime (never bundled); these are the few calls we use.
export const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";

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

export async function loadPyodide(): Promise<Pyodide> {
  const module = (await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`)) as {
    loadPyodide(options: { indexURL: string }): Promise<Pyodide>;
  };
  return module.loadPyodide({ indexURL: PYODIDE_URL });
}
