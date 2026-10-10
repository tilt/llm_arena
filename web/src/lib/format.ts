const ok = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);

export const pct = (v: number | null | undefined, digits = 0) => (ok(v) ? `${(v * 100).toFixed(digits)}%` : "–");
export const num = (v: number | null | undefined, digits = 2) =>
  ok(v) ? v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "–";
export const usd = (v: number | null | undefined) => (ok(v) ? (v < 0.01 && v > 0 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`) : "–");
// "not priced": a self-hosted model's cost is unknown (your hardware), not zero; one word everywhere (design 13.10).
export const NOT_PRICED = "not priced";
export const perMtok = (input: number | null | undefined, output: number | null | undefined) =>
  ok(input) && ok(output) ? (input === 0 && output === 0 ? NOT_PRICED : `$${input} / $${output}`) : "unknown";
