import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const source = await readFile(new URL("../src/engine/pyodide-assets.ts", import.meta.url), "utf8");
const coreFiles = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"];
const lock = JSON.parse(await readFile(`${root}/node_modules/pyodide/pyodide-lock.json`, "utf8"));
const failures = [];

for (const file of coreFiles) {
  const bytes = await readFile(`${root}/node_modules/pyodide/${file}`);
  const digest = createHash("sha256").update(bytes).digest("hex");
  if (!source.includes(`file: "${file}", sha256: "${digest}"`)) failures.push(`${file}: manifest digest mismatch`);
}
for (const entry of Object.values(lock.packages)) {
  if (source.includes(`file: "${entry.file_name}"`) && !source.includes(`sha256: "${entry.sha256}"`)) {
    failures.push(`${entry.file_name}: lockfile digest mismatch`);
  }
}
const manifestWheels = [...source.matchAll(/file: "([^"]+\.whl)"/g)].map((match) => match[1]);
for (const file of manifestWheels) {
  if (!Object.values(lock.packages).some((entry) => entry.file_name === file)) failures.push(`${file}: absent from lockfile`);
}
if (failures.length) throw new Error(`Pyodide asset verification failed:\n${failures.join("\n")}`);
process.stdout.write(`verified ${coreFiles.length} core assets and ${manifestWheels.length} pinned wheels\n`);
