import { loadPyodide } from "pyodide";
const py = await loadPyodide();
const t = performance.now();
await py.loadPackage(["duckdb"]);
const url = "https://huggingface.co/datasets/openai/gsm8k/resolve/740312add88f781978c0658806c59bc2815b9866/main/test-00000-of-00001.parquet";
const bytes = new Uint8Array(await (await fetch(url)).arrayBuffer());
py.FS.writeFile("/tmp/gsm8k.parquet", bytes);
console.log(`duckdb loaded + downloaded ${(bytes.length/1e6).toFixed(1)} MB in ${((performance.now()-t)/1000).toFixed(1)}s`);
console.log(py.runPython(`
import duckdb
with duckdb.connect() as db:
    rows = db.execute("SELECT count(*), any_value(question) FROM read_parquet('/tmp/gsm8k.parquet')").fetchone()
f"{rows[0]} rows; e.g. {rows[1][:60]}"`));
