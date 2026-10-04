export const MAX_SANDBOX_CODE_BYTES = 1024 * 1024;
export const MAX_SANDBOX_FILES_JSON_BYTES = 28 * 1024 * 1024;
export const MAX_SANDBOX_COLLECT_JSON_BYTES = 64 * 1024;
export const MAX_SANDBOX_RESULT_BYTES = 28 * 1024 * 1024;

export type SandboxNetworkIsolation = "isolated" | "not network-isolated";

export type SandboxRequest =
  | { kind: "init"; requestId: string }
  | { kind: "execute"; requestId: string; code: string; files: string; collect: string };

export type SandboxReply =
  | { kind: "ready"; requestId: string; initMs: number; networkIsolation: SandboxNetworkIsolation }
  | { kind: "result"; requestId: string; result: string }
  | { kind: "error"; requestId: string; error: string };

const encoder = new TextEncoder();

export function byteLength(value: string): number {
  return encoder.encode(value).byteLength;
}

export function requestId(): string {
  return crypto.randomUUID();
}

export function validateSandboxRequest(value: unknown): SandboxRequest {
  if (!isRecord(value) || !validRequestId(value.requestId) || typeof value.kind !== "string") {
    throw new Error("invalid sandbox request envelope");
  }
  if (value.kind === "init") return { kind: "init", requestId: value.requestId };
  if (value.kind !== "execute" || typeof value.code !== "string" || typeof value.files !== "string"
      || typeof value.collect !== "string") {
    throw new Error("invalid sandbox request");
  }
  if (byteLength(value.code) > MAX_SANDBOX_CODE_BYTES) throw new Error("sandbox code exceeds input limit");
  if (byteLength(value.files) > MAX_SANDBOX_FILES_JSON_BYTES) throw new Error("sandbox files exceed input limit");
  if (byteLength(value.collect) > MAX_SANDBOX_COLLECT_JSON_BYTES) throw new Error("sandbox collect list exceeds input limit");
  return { kind: "execute", requestId: value.requestId, code: value.code, files: value.files, collect: value.collect };
}

export function validateSandboxReply(value: unknown): SandboxReply {
  if (!isRecord(value) || !validRequestId(value.requestId) || typeof value.kind !== "string") {
    throw new Error("invalid sandbox response envelope");
  }
  if (value.kind === "ready") {
    if (typeof value.initMs !== "number" || !Number.isFinite(value.initMs) || value.initMs < 0
        || (value.networkIsolation !== "isolated" && value.networkIsolation !== "not network-isolated")) {
      throw new Error("invalid sandbox ready response");
    }
    return { kind: "ready", requestId: value.requestId, initMs: value.initMs,
      networkIsolation: value.networkIsolation };
  }
  if (value.kind === "result") {
    if (typeof value.result !== "string" || byteLength(value.result) > MAX_SANDBOX_RESULT_BYTES) {
      throw new Error("invalid or oversized sandbox result");
    }
    return { kind: "result", requestId: value.requestId, result: value.result };
  }
  if (value.kind === "error" && typeof value.error === "string" && byteLength(value.error) <= 16 * 1024) {
    return { kind: "error", requestId: value.requestId, error: value.error };
  }
  throw new Error("invalid sandbox response");
}

function validRequestId(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9-]{16,64}$/i.test(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
