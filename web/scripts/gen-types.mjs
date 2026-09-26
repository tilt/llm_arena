// Generate src/lib/contracts.ts from ../contracts/schemas/*.schema.json (exported by `arena contracts`).
// All schemas are merged into one root so shared types (ModelSpec, Score, ...) are emitted once.
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { compile } from "json-schema-to-typescript";

const dir = new URL("../../contracts/schemas/", import.meta.url).pathname;
// Pydantic titles every property; json2ts would turn each into a type alias (Name1, Name2, ...).
// Keep titles only on definitions, where they name the generated interfaces.
function stripTitles(node) {
  if (Array.isArray(node)) return node.map(stripTitles);
  if (node === null || typeof node !== "object") return node;
  const out = {};
  for (const [key, value] of Object.entries(node)) {
    if (key === "title") continue;
    out[key] = key === "properties" || key === "$defs"
      ? Object.fromEntries(Object.entries(value).map(([k, v]) => [k, stripTitles(v)]))
      : stripTitles(value);
  }
  return out;
}

const defs = {};
const roots = {};
for (const file of readdirSync(dir).filter((f) => f.endsWith(".schema.json")).sort()) {
  const name = file.replace(".schema.json", "");
  const { $defs = {}, ...schema } = JSON.parse(readFileSync(join(dir, file), "utf8"));
  for (const [defName, def] of Object.entries($defs)) defs[defName] = { ...stripTitles(def), title: defName };
  defs[name] = { ...stripTitles(schema), title: name };
  roots[name] = { $ref: `#/$defs/${name}` };
}
const root = { title: "Contracts", type: "object", properties: roots, additionalProperties: false, $defs: defs };
const ts = await compile(root, "Contracts", {
  bannerComment: "/* Generated from contracts/schemas by `npm run contracts`. Do not edit. */",
  additionalProperties: false,
  unreachableDefinitions: true,
  strictIndexSignatures: true,
});
writeFileSync(new URL("../src/lib/contracts.ts", import.meta.url), ts);
console.log(`wrote src/lib/contracts.ts (${Object.keys(roots).length} root types, ${Object.keys(defs).length} definitions)`);
