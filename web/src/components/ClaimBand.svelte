<script lang="ts">
  import { untrack } from "svelte";
  // The claim action band above a finished run's report (design 7.2): a Beat-this run offers to post its reproduction
  // (2.4, R16, 13.5); any other finished run offers Share as claim with its reasons (2.5, 13.9).
  import { app } from "../lib/app.svelte";
  import {
    GitHub, GitHubFailure, claimRunNote, failureText, gistLink, githubToken, inlineLink, nameProblem, postedNote,
    rememberName, rememberedNames, roleLabel, savePostedNote, seenIds, setGithubToken, suggestName,
    type PostedNote,
  } from "../lib/claims";
  import type { Claim, ClaimDraft, CreatedGist, ReproDraft, RunBundle } from "../lib/contracts";
  import KeyPanel from "./KeyPanel.svelte";

  // onposted: the claim page re-reads its thread so the new reproduction shows (2.4).
  let { runId, bundle, onposted }: { runId: string; bundle: RunBundle; onposted?: () => void } = $props();

  interface ClaimRef { gist_id?: string | null; revision?: string | null; claim_hash: string }
  const config = $derived((() => { try { return JSON.parse(String(bundle.run.config_json ?? "{}")) as { claim_ref?: ClaimRef }; } catch { return {}; } })());
  const ref = $derived(config.claim_ref ?? null);
  const mode = $derived(app.mode === "local" ? "local" : "browser");
  const github = $derived(new GitHub(mode, githubToken));
  // The Pages token lives in a module variable (this tab's memory); this flag makes the band react when it is set.
  let tokenSet = $state(Boolean(githubToken()));
  const githubMissing = $derived(mode === "local" ? (app.runtime?.keys?.github ?? "missing") === "missing" : !tokenSet);

  let busy = $state(false);
  let error = $state("");
  let tokenDraft = $state("");
  let askToken = $state(false);
  let copied = $state("");

  // ---- reproduction of a claim --------------------------------------------------------------------------------------
  let claimText = $state<string | null>(null);
  let repro = $state<ReproDraft | null>(null);
  let posted = $state<PostedNote | null>(null);
  let postedState = $state<"checking" | "found" | "removed" | "unknown">("checking");
  let postedWhy = $state("");
  let variantShare = $state<ClaimDraft | null>(null);

  // ---- share as claim ---------------------------------------------------------------------------------------------------
  let draft = $state<ClaimDraft | null>(null);
  let names = $state<Record<string, string>>({});
  let shared = $state<CreatedGist | null>(null);
  let postButton = $state<HTMLButtonElement | null>(null);

  async function load() {
    error = "";
    busy = true;
    try {
      if (ref) await loadRepro(); else await loadShare();
    } catch (e) {
      error = e instanceof GitHubFailure ? failureText(e) : e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  async function loadRepro() {
    const note = claimRunNote(runId);
    claimText = note?.claim ?? (ref?.gist_id && ref.revision ? (await github.claim(ref.gist_id, ref.revision)).claim : null);
    if (!claimText) return;
    posted = postedNote(runId);
    if (posted && ref?.gist_id) void checkPosted(posted);
    repro = await app.backend!.reproDraft(runId, { claim: claimText, seen: [] });
    if (repro.variant_config) {
      variantShare = await app.backend!.claimDraft(runId, { names: rememberedNames(), config: repro.variant_config });
    }
  }

  async function checkPosted(note: PostedNote) {
    postedState = "checking";
    try {
      postedState = (await github.comment(note.gist_id, note.comment_id)) ? "found" : "removed";
    } catch (e) {
      postedState = "unknown";
      postedWhy = e instanceof GitHubFailure ? failureText(e) : String(e);
    }
  }

  async function loadShare() {
    const first = await app.backend!.claimDraft(runId, { names: {} });
    const remembered = rememberedNames();
    const local = first.self_hosted ?? [];
    names = Object.fromEntries(local.map((key) => [key, remembered[key] ?? suggestName(key.split(":").slice(1).join(":"))]));
    draft = local.length ? await app.backend!.claimDraft(runId, { names }) : first;
  }

  // Reload when the run or the engine changes; load() reads and writes this component's state, so it runs untracked
  // (otherwise each write would re-run the effect).
  $effect(() => {
    void runId;
    void bundle;
    if (app.backend) untrack(() => void load());
  });

  async function redraft() {
    if (Object.values(names).some((name) => nameProblem(name))) return;
    draft = await app.backend!.claimDraft(runId, { names });
  }

  const nameErrors = $derived(Object.fromEntries(Object.entries(names).map(([local, name]) => [local, nameProblem(name)])));
  const preview = $derived((() => {
    if (!draft?.claim_json) return null;
    const claim = JSON.parse(draft.claim_json) as Claim;
    return Object.entries(claim.setup.roles).map(([role, spec]) => `${role} = ${spec ? roleLabel(spec) : "?"}`).join(" · ");
  })());

  function useToken() {
    setGithubToken(tokenDraft);
    tokenSet = Boolean(githubToken());
    tokenDraft = "";
    askToken = false;
    postButton?.focus();
  }

  async function post() {
    if (!claimText || !ref?.gist_id || !ref.revision) return;
    if (githubMissing) { askToken = true; return; }
    busy = true;
    error = "";
    try {
      const gist = await github.claim(ref.gist_id, ref.revision);
      const comments = await github.thread(ref.gist_id, gist.comments);
      const stats = await app.backend!.claimThread({ claim: claimText, comments: comments as unknown as Record<string, unknown>[],
        author: gist.owner, total: gist.comments });
      const fresh = await app.backend!.reproDraft(runId, { claim: claimText, seen: seenIds(stats.rows) });
      if (!fresh.block) { repro = fresh; return; }
      const comment = await github.post(ref.gist_id, fresh.block);
      posted = { gist_id: ref.gist_id, comment_id: comment.id, claim_hash: ref.claim_hash, posted_at: new Date().toISOString(),
        html_url: comment.html_url };
      savePostedNote(runId, posted);
      postedState = "found";
      onposted?.();
    } catch (e) {
      error = e instanceof GitHubFailure ? failureText(e) : e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  async function share(text: string) {
    if (githubMissing) { askToken = true; return; }
    busy = true;
    error = "";
    try {
      const claim = JSON.parse(text) as Claim;
      shared = await github.create(text, `llm_arena claim · ${claim.scenario} v${claim.scenario_version}`);
      for (const [local, name] of Object.entries(names)) rememberName(local, name);
    } catch (e) {
      error = e instanceof GitHubFailure ? failureText(e) : e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text);
      copied = what;
    } catch {
      copied = "";
    }
  }

  const download = (text: string) => URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const claimLink = $derived(ref?.gist_id && ref.revision ? `#/claim/gist/${ref.gist_id}@${ref.revision}` : claimText ? inlineLink(claimText, "") : null);
</script>

<section class="band" aria-labelledby="claim-band-title">
  {#if ref}
    <h2 id="claim-band-title">Reproduction of a claim</h2>
    {#if busy && !repro}<p class="muted" role="status">Checking whether this run can be posted…</p>{/if}
    {#if !busy && !claimText && !error}<p class="note">This run reproduces a claim this browser doesn't have. Open the claim's link to post it.</p>{/if}
    {#if repro && claimText}
      {#if posted}
        {#if postedState === "checking"}<p><span class="pill" aria-live="polite">checking…</span></p>
        {:else if postedState === "found"}<p aria-live="polite">Posted · <a href={posted.html_url || claimLink || "#"} target="_blank" rel="noopener">view on GitHub</a></p>
        {:else if postedState === "removed"}
          <p class="note" role="status">Your reproduction is no longer in the thread (removed by the gist owner or you).</p>
        {:else}<p class="muted">Posted · couldn't check the thread now ({postedWhy})</p>{/if}
        <p class="muted small">Posted status is remembered in this browser only.</p>
      {/if}
      {#if repro.block}
        <div class="actions">
          {#if ref.gist_id && (!posted || postedState === "removed")}
            <button class="primary" bind:this={postButton} onclick={post} disabled={busy}>{busy ? "Posting…" : posted ? "Post again" : "Post reproduction"}</button>
          {/if}
          <button onclick={() => copy(repro!.block!, "comment")}>Copy comment</button>
          {#if claimLink}<a href={claimLink}>Open claim</a>{/if}
          {#if copied === "comment"}<span class="muted small" role="status">Copied</span>{/if}
        </div>
        {#if !ref.gist_id}<p class="muted small">This claim came as a link without a gist: paste the comment under the claim's gist to post it.</p>{/if}
      {:else}
        <p class="note">This run can't be posted as a reproduction: {(repro.reasons ?? []).join("; ")}</p>
        {#if claimLink}<p><a href={claimLink}>Open claim</a></p>{/if}
      {/if}
      {#if variantShare?.claim_json}
        <p><button onclick={() => share(variantShare!.claim_json!)} disabled={busy}>Share my variant as a new claim</button></p>
      {/if}
    {/if}
  {:else}
    <h2 id="claim-band-title">Share as claim</h2>
    {#if busy && !draft}<p class="muted" role="status">Checking whether this run can be shared…</p>{/if}
    {#if draft}
      {#each Object.keys(names) as local (local)}
        <div class="name">
          <label for={`compare-${local}`}>{local} · compare as</label>
          <input id={`compare-${local}`} bind:value={names[local]} onchange={redraft} aria-describedby={`compare-hint-${local}`} />
          <span id={`compare-hint-${local}`} class="muted small" class:fail={nameErrors[local]}>
            {nameErrors[local] || "lowercase letters, digits, . and -; up to 64"}</span>
        </div>
        <p class="muted small">Others match this role by this name. Your endpoint's name and address aren't shared.</p>
      {/each}
      {#if shared}
        {@const link = gistLink(shared.gist_id, shared.revision)}
        <div class="actions">
          <input class="link" readonly value={link} aria-label="Claim link" />
          <button class="primary" onclick={() => copy(link, "link")}>Copy link</button>
          <a href={shared.html_url} target="_blank" rel="noopener">View gist</a>
          {#if copied === "link"}<span class="muted small" role="status">Copied</span>{/if}
        </div>
      {:else if draft.claim_json}
        {#if preview}<p class="small">Publishes: {preview}</p>{/if}
        <div class="actions">
          <button class="primary" onclick={() => share(draft!.claim_json!)} disabled={busy || Object.values(nameErrors).some(Boolean)}>Share as claim</button>
          <span class="muted small">Creates a public gist{mode === "local" ? "" : " under your GitHub account"}.</span>
        </div>
        {#if githubMissing && mode === "browser"}
          <p class="muted small">No token? <a href={download(draft.claim_json)} download="claim.json">Download claim.json</a>, create a public
            gist with it at gist.github.com (file name <code>claim.json</code>), then share
            <code>#/claim/gist/&lt;id&gt;@&lt;revision&gt;</code> on this site. Or share this
            <a href={inlineLink(draft.claim_json, "")}>link without a gist</a> (no reproduction thread).</p>
        {/if}
      {:else}
        <button class="primary" disabled aria-describedby="share-reasons">Share as claim</button>
        <div id="share-reasons" class="note">
          {#each draft.reasons ?? [] as reason}<p>{reason[0]?.toUpperCase()}{reason.slice(1)}.</p>{/each}
        </div>
      {/if}
    {/if}
  {/if}
  {#if askToken}
    {#if mode === "local"}
      <KeyPanel providers={["github"]} heading="Add a GitHub token to post" onset={() => { askToken = false; postButton?.focus(); }} />
    {:else}
      <div class="token">
        <label for="gh-token">GitHub token (fine-grained, Gists permission)</label>
        <input id="gh-token" type="password" autocomplete="off" bind:value={tokenDraft} aria-describedby="gh-token-warn" />
        <button onclick={useToken} disabled={!tokenDraft.trim()}>Use</button>
        <p id="gh-token-warn" class="muted small">This token can read, edit and delete all your gists. It stays in this tab.</p>
      </div>
    {/if}
  {/if}
  {#if error}<p class="error" role="alert">{error} <button onclick={load}>Retry</button></p>{/if}
</section>

<style>
  .band { margin: 12px 0 16px; padding: 12px 0; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
  .band h2 { margin: 0 0 8px; font-size: 16px; }
  .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .name, .token { display: grid; gap: 4px; max-width: 520px; margin: 8px 0; }
  .link { min-width: min(100%, 420px); font-family: var(--mono, monospace); font-size: 12px; }
  button, input { min-height: 36px; }
  @media (max-width: 640px) { button, input { min-height: 44px; } }
</style>
