// Phase 0 spike, step 1: which llm_arena modules import cleanly inside Pyodide?
// Usage: node probe_imports.mjs dist/llm_arena-0.1.0-py3-none-any.whl
import { readFileSync } from "node:fs";
import { basename } from "node:path";
import { loadPyodide } from "pyodide";

const wheel = process.argv[2];
const started = performance.now();
const py = await loadPyodide();
await py.loadPackage(["micropip", "pydantic", "pyyaml", "numpy"]);
const loadedAt = performance.now();
py.FS.writeFile(`/tmp/${basename(wheel)}`, readFileSync(wheel));
const micropip = py.pyimport("micropip");
await micropip.install(`emfs:/tmp/${basename(wheel)}`, { deps: false });
// BM25 is vendored now; no extra packages
console.log(`pyodide ready ${((loadedAt - started) / 1000).toFixed(1)}s, wheel installed ${((performance.now() - loadedAt) / 1000).toFixed(1)}s`);

const result = await py.runPythonAsync(`
import importlib, pkgutil, traceback, llm_arena
report = {}
for info in pkgutil.walk_packages(llm_arena.__path__, "llm_arena."):
    try:
        importlib.import_module(info.name)
        report[info.name] = "ok"
    except Exception as exc:
        report[info.name] = f"{type(exc).__name__}: {exc}"
import json; json.dumps(report)
`);
const report = JSON.parse(result);
const failed = Object.entries(report).filter(([, v]) => v !== "ok");
console.log(`${Object.keys(report).length - failed.length}/${Object.keys(report).length} modules import`);
for (const [name, error] of failed) console.log(`  FAIL ${name}: ${error}`);
