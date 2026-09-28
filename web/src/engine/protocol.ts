// Messages between the UI thread and the engine worker.
export type EngineMethod =
  | "init" | "runtime" | "scenarios" | "models" | "set_key" | "clear_key" | "estimate" | "start_run"
  | "cancel" | "runs" | "bundle" | "leaderboard" | "selftest";

export interface EngineRequest { id: number; method: EngineMethod; args: unknown[] }
export type EngineReply =
  | { kind: "result"; id: number; result: unknown }
  | { kind: "error"; id: number; error: string }
  | { kind: "event"; raw: string }
  | { kind: "status"; message: string };

