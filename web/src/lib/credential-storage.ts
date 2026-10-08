import type { SaveEndpoint } from "./contracts";

const REMEMBERED_KEYS = "llm-arena.keys";
// Endpoint URLs (and their keys, if entered) can name a private server, so they follow the same origin policy as keys:
// remembered only on the trusted origin, never on a shared one such as github.io.
const REMEMBERED_ENDPOINTS = "llm-arena.endpoints";
const REMOVAL_NOTICE = "llm-arena.keys-removed-notice";
const BUILD_ORIGIN = (import.meta.env.VITE_CREDENTIAL_ORIGIN as string | undefined)?.trim() ?? "";

export interface CredentialPolicy {
  canRemember: boolean;
  removedLegacyKeys: boolean;
}

export function credentialStorageAllowed(
  origin = window.location.origin,
  trustedOrigin = BUILD_ORIGIN,
): boolean {
  return trustedOrigin !== "" && origin === trustedOrigin;
}

/** Delete the legacy entry on every untrusted origin without parsing or forwarding its contents. */
export function enforceCredentialStorage(
  origin = window.location.origin,
  storage: Pick<Storage, "getItem" | "removeItem"> = window.localStorage,
  notices: Pick<Storage, "getItem" | "setItem"> = window.sessionStorage,
  trustedOrigin = BUILD_ORIGIN,
): CredentialPolicy {
  const canRemember = credentialStorageAllowed(origin, trustedOrigin);
  if (canRemember) return { canRemember, removedLegacyKeys: false };
  try {
    const existed = storage.getItem(REMEMBERED_KEYS) !== null;
    storage.removeItem(REMEMBERED_KEYS);
    storage.removeItem(REMEMBERED_ENDPOINTS);
    if (!existed || notices.getItem(REMOVAL_NOTICE) !== null) {
      return { canRemember, removedLegacyKeys: false };
    }
    notices.setItem(REMOVAL_NOTICE, "1");
    return { canRemember, removedLegacyKeys: true };
  } catch {
    return { canRemember, removedLegacyKeys: false };
  }
}

export function readRememberedKeys(storage: Pick<Storage, "getItem"> = window.localStorage): Record<string, string> {
  try {
    const value: unknown = JSON.parse(storage.getItem(REMEMBERED_KEYS) ?? "{}");
    if (value === null || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(
      Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
    );
  } catch {
    return {};
  }
}

export function writeRememberedKeys(
  keys: Record<string, string>,
  storage: Pick<Storage, "setItem" | "removeItem"> = window.localStorage,
): void {
  if (Object.keys(keys).length) storage.setItem(REMEMBERED_KEYS, JSON.stringify(keys));
  else storage.removeItem(REMEMBERED_KEYS);
}

/** Remembered endpoints by id, each with its key when one was entered. */
export function readRememberedEndpoints(storage: Pick<Storage, "getItem"> = window.localStorage): Record<string, SaveEndpoint> {
  try {
    const value: unknown = JSON.parse(storage.getItem(REMEMBERED_ENDPOINTS) ?? "{}");
    if (value === null || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, SaveEndpoint] => {
      const endpoint = entry[1] as Partial<SaveEndpoint> | null;
      return typeof endpoint === "object" && endpoint !== null && typeof endpoint.base_url === "string";
    }));
  } catch {
    return {};
  }
}

export function writeRememberedEndpoints(
  endpoints: Record<string, SaveEndpoint>,
  storage: Pick<Storage, "setItem" | "removeItem"> = window.localStorage,
): void {
  if (Object.keys(endpoints).length) storage.setItem(REMEMBERED_ENDPOINTS, JSON.stringify(endpoints));
  else storage.removeItem(REMEMBERED_ENDPOINTS);
}
