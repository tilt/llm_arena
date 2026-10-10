// Shareable claims on the page: links, the pre-engine preview, GitHub I/O and per-browser notes.
// The engine (llm_arena/claims.py) is the only validator; everything here is plumbing and display.
// GitHub: on Pages the page fetches api.github.com directly; in the local app (connect-src 'self') it goes through
// the server's bounded adapter at /api/claims/gists/...
import type { CatalogItem } from "./backend";
import type { ClaimRole, CreatedGist, GistClaim, GistComment, ThreadRow } from "./contracts";

export type ClaimLink = { kind: "gist"; id: string; revision: string } | { kind: "inline"; text: string };
export type Mode = "local" | "browser";

const GIST_ID = /^[0-9a-f]{20,32}$/;
const REVISION = /^[0-9a-f]{40}$/;
const API = "https://api.github.com/gists";
export const MAX_PAGES = 3;
export const PER_PAGE = 100;
export const COMPARE_NAME = /^[a-z0-9][a-z0-9.-]{0,63}$/;
const MAX_INLINE = 256 * 1024;

// ---- links ---------------------------------------------------------------------------------------------------------
/** The claim a `#/claim/...` hash points at, or null: `gist/<id>@<revision>` or `<base64url of the claim JSON>`. */
export function parseClaimHash(rest: string): ClaimLink | null {
  if (rest.startsWith("gist/")) {
    const [id, revision] = rest.slice(5).split("@");
    return id && revision && GIST_ID.test(id) && REVISION.test(revision) ? { kind: "gist", id, revision } : null;
  }
  if (!rest || rest.length > MAX_INLINE * 2) return null;
  try {
    return { kind: "inline", text: fromBase64Url(rest) };
  } catch {
    return null;
  }
}

export function gistLink(id: string, revision: string, origin = pageBase()): string {
  return `${origin}#/claim/gist/${id}@${revision}`;
}

export function inlineLink(claim: string, origin = pageBase()): string {
  return `${origin}#/claim/${toBase64Url(claim)}`;
}

function pageBase(): string {
  return typeof location === "undefined" ? "" : `${location.origin}${location.pathname}`;
}

export function toBase64Url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function fromBase64Url(value: string): string {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("not base64url");
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((value.length + 3) % 4);
  const binary = atob(padded);
  return new TextDecoder("utf-8", { fatal: true }).decode(Uint8Array.from(binary, (c) => c.charCodeAt(0)));
}

// ---- preview before the engine validates (design 2.1) -----------------------------------------------------------
export interface ClaimPreview {
  scenario: string;
  version: string;
  tasks: number;
  roles: { role: string; model: string }[];
  passRate: number;
  costPerTask: number;
}

const short = (value: unknown, max: number): value is string => typeof value === "string" && value.length > 0 && value.length <= max;
const rate = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;

/** A narrow, type-checked read of an unvalidated claim, shown as plain text while the engine loads. Anything that
 *  doesn't fit returns null: no preview, the page waits for the engine. */
export function previewOf(text: string): ClaimPreview | null {
  if (text.length > MAX_INLINE) return null;
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return null;
  }
  if (!raw || typeof raw !== "object") return null;
  const claim = raw as Record<string, unknown>;
  const setup = claim.setup as { roles?: unknown } | undefined;
  const result = claim.result as { pass_rate?: unknown; cost_usd_per_task?: unknown } | undefined;
  if (!short(claim.scenario, 64) || !short(claim.scenario_version, 16) || !Array.isArray(claim.tasks)) return null;
  if (claim.tasks.length < 1 || claim.tasks.length > 500 || !setup || typeof setup.roles !== "object" || !setup.roles) return null;
  if (!result || !rate(result.pass_rate) || typeof result.cost_usd_per_task !== "number" || result.cost_usd_per_task < 0) return null;
  const roles = Object.entries(setup.roles as Record<string, unknown>);
  if (roles.length < 1 || roles.length > 16) return null;
  const lines: { role: string; model: string }[] = [];
  for (const [role, spec] of roles) {
    const model = (spec as { model?: unknown; provider?: unknown } | null)?.model;
    const provider = (spec as { provider?: unknown } | null)?.provider;
    if (!short(role, 41) || !short(model, 200) || !short(provider, 20)) return null;
    lines.push({ role, model: provider === "self_hosted" ? `self-hosted ${model}` : `${provider}:${model}` });
  }
  return {
    scenario: claim.scenario, version: claim.scenario_version, tasks: claim.tasks.length, roles: lines,
    passRate: result.pass_rate, costPerTask: result.cost_usd_per_task,
  };
}

// ---- GitHub ---------------------------------------------------------------------------------------------------------
export type GitHubFailureKind = "invalid" | "unreachable" | "server" | "throttled" | "rate_limited" | "not_found" | "unauthorized";

export class GitHubFailure extends Error {
  constructor(readonly kind: GitHubFailureKind, message: string, readonly retryAfterS: number | null = null) {
    super(message);
  }
}

/** The plain-words message for each failure state (design 2.2, D6). */
export function failureText(failure: GitHubFailure): string {
  switch (failure.kind) {
    case "not_found": return "This claim no longer exists. The gist was deleted or the link is wrong.";
    case "unreachable": return "GitHub can't be reached right now. Check your connection and retry.";
    case "server": return "GitHub had an error. Try again shortly.";
    case "throttled": return `GitHub asks to wait${failure.retryAfterS ? ` ${failure.retryAfterS} s` : ""} before the next request.`;
    case "rate_limited": return "GitHub's limit of 60 requests per hour without a token is used up. Add a token, or wait"
      + `${failure.retryAfterS ? ` ${Math.ceil(failure.retryAfterS / 60)} min` : ""}.`;
    case "unauthorized": return "GitHub refused the token. It needs the Gists permission.";
    default: return failure.message;
  }
}

/** Ids reach a URL that may carry the visitor's token, so they are checked here and not only by the router: a
 * hostile imported run file could otherwise point a post at another api.github.com path. */
function checkIds(id: string, revision?: string): void {
  if (!GIST_ID.test(id) || (revision !== undefined && !REVISION.test(revision))) {
    throw new GitHubFailure("invalid", "not a gist id or revision");
  }
}

/** Where GitHub calls go: straight to api.github.com on Pages, through the local server otherwise. */
export class GitHub {
  constructor(private readonly mode: Mode, private readonly token: () => string | null = () => null) {}

  async claim(id: string, revision: string): Promise<GistClaim> {
    checkIds(id, revision);
    if (this.mode === "local") return this.local(`/api/claims/gists/${id}/${revision}`);
    const pinned = await this.direct(`${API}/${id}/${revision}`) as { files?: Record<string, { content?: string; truncated?: boolean }>; owner?: { login?: string } };
    const head = await this.direct(`${API}/${id}`) as { history?: { version?: string }[]; comments?: number; html_url?: string };
    const file = pinned.files?.["claim.json"];
    if (!file || typeof file.content !== "string") throw new GitHubFailure("not_found", "this gist has no claim.json");
    if (file.truncated) throw new GitHubFailure("invalid", "claim.json is too large to be a claim");
    return {
      claim: file.content, owner: String(pinned.owner?.login ?? ""), head_revision: String(head.history?.[0]?.version ?? revision),
      comments: Number(head.comments ?? 0), html_url: String(head.html_url ?? ""),
    };
  }

  async comments(id: string, page: number): Promise<GistComment[]> {
    checkIds(id);
    if (!Number.isInteger(page) || page < 1 || page > MAX_PAGES) throw new GitHubFailure("invalid", "no such comment page");
    if (this.mode === "local") return this.local(`/api/claims/gists/${id}/comments?page=${page}`);
    const rows = await this.direct(`${API}/${id}/comments?per_page=${PER_PAGE}&page=${page}`);
    return Array.isArray(rows) ? rows.map(commentOf) : [];
  }

  /** The thread's first `MAX_PAGES` pages (at most 300 comments); `total` says whether more exist. */
  async thread(id: string, total: number): Promise<GistComment[]> {
    const pages = Math.min(MAX_PAGES, Math.ceil(total / PER_PAGE));  // 0 comments: no request at all
    const all: GistComment[] = [];
    for (let page = 1; page <= pages; page++) all.push(...await this.comments(id, page));
    return all;
  }

  /** One comment, or null when GitHub says it is gone (design 13.5). */
  async comment(id: string, commentId: number): Promise<GistComment | null> {
    checkIds(id);
    if (!Number.isSafeInteger(commentId) || commentId < 1) throw new GitHubFailure("invalid", "not a comment id");
    try {
      return this.mode === "local"
        ? await this.local<GistComment>(`/api/claims/gists/${id}/comments/${commentId}`)
        : commentOf(await this.direct(`${API}/${id}/comments/${commentId}`));
    } catch (error) {
      if (error instanceof GitHubFailure && error.kind === "not_found") return null;
      throw error;
    }
  }

  async create(claim: string, description: string): Promise<CreatedGist> {
    if (this.mode === "local") return this.local("/api/claims/gists", { claim });
    const created = await this.direct(API, { description, public: true, files: { "claim.json": { content: claim } } }) as {
      id?: string; history?: { version?: string }[]; html_url?: string; owner?: { login?: string };
    };
    return { gist_id: String(created.id ?? ""), revision: String(created.history?.[0]?.version ?? ""),
      html_url: String(created.html_url ?? ""), owner: String(created.owner?.login ?? "") };
  }

  async post(id: string, body: string): Promise<GistComment> {
    checkIds(id);
    if (this.mode === "local") return this.local(`/api/claims/gists/${id}/comments`, { body });
    return commentOf(await this.direct(`${API}/${id}/comments`, { body }));
  }

  private async local<T>(path: string, body?: unknown): Promise<T> {
    let response: Response;
    try {
      response = await fetch(path, {
        method: body === undefined ? "GET" : "POST", credentials: "same-origin",
        headers: body === undefined ? undefined : { "content-type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new GitHubFailure("unreachable", "the local arena server can't be reached");
    }
    if (response.ok) return await response.json() as T;
    const detail = await response.json().then((d: { detail?: unknown }) => d.detail).catch(() => null);
    if (detail && typeof detail === "object" && "kind" in detail) {
      const d = detail as { kind: GitHubFailureKind; message?: string; retry_after_s?: number | null };
      throw new GitHubFailure(d.kind, String(d.message ?? d.kind), d.retry_after_s ?? null);
    }
    throw new GitHubFailure(response.status === 401 ? "unauthorized" : "invalid", typeof detail === "string" ? detail : response.statusText);
  }

  private async direct(url: string, body?: unknown): Promise<unknown> {
    const headers: Record<string, string> = { Accept: "application/vnd.github+json" };
    const token = this.token();
    if (token) headers.Authorization = `Bearer ${token}`;
    else if (body !== undefined) throw new GitHubFailure("unauthorized", "posting needs a GitHub token with the Gists permission");
    let response: Response;
    try {
      response = await fetch(url, {
        method: body === undefined ? "GET" : "POST", headers: body === undefined ? headers : { ...headers, "content-type": "application/json" },
        // no-store: a claim's head revision and thread must be fresh, and a cached unauthenticated answer must
        // never stand in for an authenticated request.
        body: body === undefined ? undefined : JSON.stringify(body), redirect: "error", credentials: "omit", cache: "no-store",
        signal: AbortSignal.timeout(10_000),
      });
    } catch {
      throw new GitHubFailure("unreachable", "GitHub can't be reached");
    }
    if (response.ok) return response.json();
    throw failureOf(response, Boolean(token));
  }
}

/** Maps a GitHub error response to a failure state (same rules as the local adapter, adapters/server/gists.py). */
export function failureOf(response: { status: number; headers: { get(name: string): string | null } }, authenticated: boolean): GitHubFailure {
  const { status } = response;
  if (status === 404) return new GitHubFailure("not_found", "not found");
  if (status === 401) return new GitHubFailure("unauthorized", "GitHub rejected the token");
  const retry = response.headers.get("retry-after");
  if ((status === 403 || status === 429) && (retry || response.headers.get("x-ratelimit-remaining") === "0")) {
    if (retry && /^\d+$/.test(retry)) return new GitHubFailure("throttled", `wait ${retry} s`, Number(retry));
    const reset = Number(response.headers.get("x-ratelimit-reset") ?? NaN);
    const wait = Number.isFinite(reset) ? Math.max(0, Math.round(reset - Date.now() / 1000)) : null;
    return new GitHubFailure(authenticated ? "throttled" : "rate_limited", "rate limit", wait);
  }
  if (status === 403) return new GitHubFailure("unauthorized", "GitHub refused this (does the token have the Gists permission?)");
  if (status >= 500) return new GitHubFailure("server", `GitHub error ${status}`);
  return new GitHubFailure("invalid", `GitHub refused the request (${status})`);
}

function commentOf(row: unknown): GistComment {
  const r = (row ?? {}) as { id?: unknown; user?: { login?: unknown }; created_at?: unknown; updated_at?: unknown; body?: unknown; html_url?: unknown };
  return {
    id: Number(r.id ?? 0), user: { login: String(r.user?.login ?? "").slice(0, 100) },
    created_at: String(r.created_at ?? "").slice(0, 40), updated_at: String(r.updated_at ?? "").slice(0, 40),
    body: String(r.body ?? "").slice(0, 65_536), html_url: String(r.html_url ?? "").slice(0, 300),
  };
}

// ---- GitHub token on Pages: this tab's memory only ------------------------------------------------------------------
let pagesToken: string | null = null;
export const githubToken = (): string | null => pagesToken;
export function setGithubToken(token: string | null): void {
  pagesToken = token?.trim() || null;
}

// ---- self-hosted names (designs 13.3, 13.15) -------------------------------------------------------------------------
export const SELF_HOSTED_SOURCES = new Set(["ollama", "lmstudio", "openai_compatible"]);

export const isSelfHosted = (item: Pick<CatalogItem, "source">): boolean => SELF_HOSTED_SOURCES.has(String(item.source));

/** The key a self-hosted model's name is remembered under: one model on one server ('gpu-box:Qwen3-14B'). */
export function localModel(item: Pick<CatalogItem, "source" | "endpoint" | "spec">): string {
  return `${item.endpoint ?? item.source}:${item.spec.model}`;
}

/** A first suggestion from the server id: 'qwen3:14b' -> 'qwen3-14b', 'Qwen/Qwen3-14B-AWQ' -> 'qwen3-14b-awq'. */
export function suggestName(modelId: string): string {
  let name = (modelId.split("/").pop() ?? modelId).toLowerCase();
  name = name.replace(/[/:_\s]+/g, "-").replace(/[^a-z0-9.-]/g, "").replace(/-{2,}/g, "-").replace(/^[-.]+|[-.]+$/g, "");
  return name.slice(0, 64).replace(/[-.]+$/, "") || "model";
}

export const nameProblem = (name: string): string =>
  COMPARE_NAME.test(name) ? "" : "Use lowercase letters, digits, . and -; up to 64.";

export function roleLabel(role: ClaimRole): string {
  const notes = [role.reasoning_effort === "none" ? "no thinking" : role.reasoning_effort ? `${role.reasoning_effort} reasoning` : "",
    role.tool_mode === "json" ? "json tools" : "", role.max_tokens ? `max ${role.max_tokens} tokens` : ""].filter(Boolean);
  const model = role.provider === "self_hosted" ? `self-hosted ${role.model} (self-declared)` : `${role.provider}:${role.model}`;
  return `${model}${notes.length ? ` · ${notes.join(", ")}` : ""}`;
}

// ---- per-browser notes (R16, 13.2, 13.15) -----------------------------------------------------------------------------
type Store = Pick<Storage, "getItem" | "setItem">;
const storage = (): Store | null => {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
};

function readMap<T>(key: string, store: Store | null = storage()): Record<string, T> {
  try {
    const value: unknown = JSON.parse(store?.getItem(key) ?? "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, T> : {};
  } catch {
    return {};
  }
}

function writeEntry<T>(key: string, id: string, value: T | null, store: Store | null = storage()): void {
  try {
    const map = readMap<T>(key, store);
    if (value === null) delete map[id]; else map[id] = value;
    store?.setItem(key, JSON.stringify(map));
  } catch {
    // Private windows and blocked storage: the note is a convenience; the page works without it.
  }
}

export interface PostedNote { gist_id: string; comment_id: number; claim_hash: string; posted_at: string; html_url?: string }
export interface ClaimRunNote { claim: string; gist_id?: string; revision?: string }

const POSTS = "arena.claimPosts";
const RUNS = "arena.claimRuns";
const NAMES = "arena.compareAs";
const MATCHES = "arena.claimMatches";

export const postedNote = (runId: string, store?: Store | null): PostedNote | null => readMap<PostedNote>(POSTS, store)[runId] ?? null;
export const savePostedNote = (runId: string, note: PostedNote | null, store?: Store | null) => writeEntry(POSTS, runId, note, store);
/** The claim a Beat-this run reproduces, so its run view can rebuild the post after a reload (hash links too). */
export const claimRunNote = (runId: string): ClaimRunNote | null => readMap<ClaimRunNote>(RUNS)[runId] ?? null;
export const saveClaimRunNote = (runId: string, note: ClaimRunNote) => writeEntry(RUNS, runId, note);
export const rememberedNames = (): Record<string, string> => readMap<string>(NAMES);
export const rememberName = (local: string, name: string) => writeEntry(NAMES, local, name);
export const lastMatch = (claimHash: string, role: string): string | null => readMap<string>(MATCHES)[`${claimHash}|${role}`] ?? null;
export const rememberMatch = (claimHash: string, role: string, ref: string) => writeEntry(MATCHES, `${claimHash}|${role}`, ref);

/** The name to prefill for a self-hosted model: remembered for this model on this server, else the same model id's
 *  name on another of your servers, else the suggestion. */
export function prefillName(item: Pick<CatalogItem, "source" | "endpoint" | "spec">, names = rememberedNames()): string {
  const key = localModel(item);
  if (names[key]) return names[key];
  const sameId = Object.entries(names).find(([local]) => local.split(":").slice(1).join(":") === item.spec.model);
  return sameId?.[1] ?? suggestName(item.spec.model);
}

/** Your self-hosted models declared under `name` (13.2 match candidates). */
export function declaredAs(name: string, models: CatalogItem[], names = rememberedNames()): CatalogItem[] {
  return models.filter((m) => isSelfHosted(m) && names[localModel(m)] === name);
}

/** The comment ids a new reproduction lists as seen: the reproductions counted (or the author's) at post time, so
 *  a later deletion of one of them becomes visible (D15). */
export const seenIds = (rows: ThreadRow[]): number[] =>
  rows.filter((r) => r.status === "counted" || r.status === "author").map((r) => r.comment_id).slice(-300);
