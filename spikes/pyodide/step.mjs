import { loadPyodide } from "pyodide";
const step = async (name, fn) => { try { const r = await fn(); console.log("ok", name); return r; } catch (e) { console.log("FAIL", name, String(e.message).slice(0, 400)); process.exit(1); } };
const py = await step("loadPyodide", () => loadPyodide());
await step("loadPackage micropip", () => py.loadPackage(["micropip"]));
await step("loadPackage pydantic", () => py.loadPackage(["pydantic", "pyyaml", "numpy", "sqlite3"]));
