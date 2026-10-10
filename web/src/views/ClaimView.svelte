<script lang="ts">
  // A shared claim (design §11-§13): what it says, how often others reproduced it, and "Beat this": re-run the
  // claimed setup with your own keys next to one swapped model, then post the reproduction to the claim's thread.
  // Renders before the in-browser engine is ready (2.1): the gist loads at once and a guarded preview shows; the
  // engine (llm_arena/claims.py) is the only validator.
  import { untrack } from "svelte";
  import BarsCI from "../components/BarsCI.svelte";
  import ClaimBand from "../components/ClaimBand.svelte";
  import KeyPanel from "../components/KeyPanel.svelte";
  import ModelRefInput from "../components/ModelRefInput.svelte";
  import ReplacementEffects from "../components/ReplacementEffects.svelte";
  import RunProgress from "../components/RunProgress.svelte";
  import { app } from "../lib/app.svelte";
  import type { CatalogItem } from "../lib/backend";
  import {
    GitHub, GitHubFailure, declaredAs, failureText, githubToken, isSelfHosted, lastMatch, localModel, nameProblem, prefillName,
    previewOf, rememberMatch, rememberName, rememberedNames, roleLabel, saveClaimRunNote, type ClaimLink,
  } from "../lib/claims";
  import type {
    Candidate, ClaimCheck, ClaimExperimentRequest, ClaimRole, Estimate, ExperimentConfig, GistClaim, GistComment, RunBundle, ThreadRow,
    TrustStats,
  } from "../lib/contracts";
  import { NOT_PRICED, pct, usd } from "../lib/format";
  import { policyOf } from "../lib/leaderboard";
  import { initialProgress, reduce, stopReason, type RunProgress as Progress } from "../lib/progress";

  let { link }: { link: ClaimLink | null } = $props();

  const mode = $derived(app.mode === "local" ? "local" : "browser");
  const github = $derived(new GitHub(mode, githubToken));

  // ---- the claim ------------------------------------------------------------------------------------------------------
  let gist = $state<GistClaim | null>(null);
  let claimText = $state<string | null>(null);
  let failure = $state<GitHubFailure | null>(null);
  let check = $state<ClaimCheck | null>(null);
  let invalid = $state("");
  let heading = $state<HTMLHeadingElement | null>(null);
  const preview = $derived(claimText ? previewOf(claimText) : null);
  const claim = $derived(check?.claim ?? null);
  const edited = $derived(link?.kind === "gist" && gist && gist.head_revision && gist.head_revision !== link.revision);

  async function fetchClaim() {
    failure = null;
    invalid = "";
    if (!link) { invalid = "This link doesn't contain a valid claim."; return; }
    if (link.kind === "inline") { claimText = link.text; return; }
    try {
      gist = await github.claim(link.id, link.revision);
      claimText = gist.claim;
    } catch (e) {
      failure = e instanceof GitHubFailure ? e : new GitHubFailure("unreachable", String(e));
    }
  }

  // GitHub first, without waiting for the engine (D11); the transport depends only on the mode (A6).
  $effect(() => {
    void link;
    if (app.mode === "detecting" || app.mode === "locked") return;
    untrack(() => {
      gist = null; claimText = null; check = null; stats = null; comments = null; threadFailure = null; threadError = "";
      estimate = null; cap = null; capTouched = false;  // a limit typed for another claim doesn't carry over
      void fetchClaim();
    });
  });

  $effect(() => {
    const backend = app.backend;
    const text = claimText;
    if (!backend || !text) return;
    untrack(() => {
      backend.claimCheck(text).then((value) => { check = value; invalid = ""; heading?.focus(); })
        .catch((e) => { invalid = e instanceof Error ? e.message : String(e); });
    });
  });

  $effect(() => { if (heading && claimText) untrack(() => heading?.focus()); });

  // ---- the thread -----------------------------------------------------------------------------------------------------
  let comments = $state<GistComment[] | null>(null);
  let threadFailure = $state<GitHubFailure | null>(null);
  let stats = $state<TrustStats | null>(null);

  let threadError = $state("");

  // GitHub allows 60 unauthenticated requests an hour: the thread is fetched once per gist load (and after a post);
  // the engine filter only re-tallies the comments already here.
  async function loadThread() {
    if (link?.kind !== "gist" || !gist) return;
    const asked = link, from = gist;
    threadFailure = null;
    try {
      const rows = await github.thread(asked.id, from.comments);
      if (link === asked && gist === from) comments = rows;  // dropped if the visitor moved on meanwhile
    } catch (e) {
      threadFailure = e instanceof GitHubFailure ? e : new GitHubFailure("unreachable", String(e));
    }
  }
  $effect(() => { if (gist) untrack(() => void loadThread()); });

  async function reloadThread() {
    if (link?.kind !== "gist") return;
    const asked = link;
    try {
      const fresh = await github.claim(asked.id, asked.revision);  // a fresh comment count; the effect re-reads the thread
      if (link === asked) gist = fresh;
    } catch (e) {
      threadFailure = e instanceof GitHubFailure ? e : new GitHubFailure("unreachable", String(e));
    }
  }

  let engineFilter = $state<"" | "pages" | "local">("");
  $effect(() => {
    const backend = app.backend, rows = comments, filter = engineFilter;
    if (!backend || !rows || !check || !gist || !claimText) return;
    const g = gist, text = claimText;
    untrack(() => {
      threadError = "";
      backend.claimThread({ claim: text, comments: rows as unknown as Record<string, unknown>[], author: g.owner, total: g.comments,
        engine: filter || null }).then((value) => { stats = value; })
        .catch((e) => { threadError = e instanceof Error ? e.message : String(e); });
    });
  });

  const selfHostedClaim = $derived(Boolean(claim && Object.values(claim.setup.roles).some((r) => r?.provider === "self_hosted")));
  const trustBars = $derived.by(() => {
    if (!claim || !stats || stats.people < 1 || stats.rate == null) return null;
    const claimed = claim.result.pass_rate;
    return [
      { label: "claimed", value: claimed, low: claimed, high: claimed, n: claim.result.trials },
      { label: `reproduced · ${stats.people} ${stats.people === 1 ? "person" : "people"}`, value: stats.rate,
        low: stats.low ?? stats.rate, high: stats.high ?? stats.rate, n: stats.trials ?? 0 },
    ];
  });

  // ---- Beat this ------------------------------------------------------------------------------------------------------
  const models = $derived<CatalogItem[]>(app.models?.models ?? []);
  let role = $state("");
  let candidate = $state("");
  let candidateName = $state("");
  let candidates = $state<Candidate[] | null>(null);
  let candidatesError = $state("");
  let matches = $state<Record<string, string>>({});
  let declareRole = $state<Record<string, string>>({});
  let cap = $state<number | null>(null);
  let capTouched = $state(false);  // a limit the visitor typed survives re-estimates
  let estimate = $state<Estimate | null>(null);
  const priced = $derived(Boolean(estimate && (estimate.needs_cap || estimate.cost_usd > 0)));  // needs_cap: also Jev
  const capSet = $derived(typeof cap === "number" && cap > 0);
  let experiment = $state<ExperimentConfig | null>(null);
  let buildError = $state("");
  let running = $state<string | null>(null);
  let progress = $state<Progress>({ ...initialProgress });
  let result = $state<RunBundle | null>(null);
  let resultHeading = $state<HTMLHeadingElement | null>(null);

  const selfHostedRoles = $derived(claim ? Object.entries(claim.setup.roles).filter(([, r]) => r?.provider === "self_hosted") as [string, ClaimRole][] : []);
  const judgeSelfHosted = $derived(claim?.judge?.provider === "self_hosted" ? claim.judge : null);

  // 13.2: the visitor's model standing in for each self-hosted role, preselecting the last one used.
  $effect(() => {
    if (!check) return;
    const names = rememberedNames();
    const next: Record<string, string> = {};
    for (const [name, spec] of [...selfHostedRoles, ...(judgeSelfHosted ? [["judge", judgeSelfHosted] as [string, ClaimRole]] : [])]) {
      const options = declaredAs(spec.model, models, names);
      const last = lastMatch(check.claim_hash, name);
      next[name] = options.find((m) => m.ref === last)?.ref ?? options[0]?.ref ?? "";
    }
    untrack(() => (matches = next));
  });

  async function loadCandidates() {
    candidates = null;
    candidatesError = "";
    if (!check || !role || !app.backend) return;
    try {
      candidates = await app.backend.claimCandidates({ claim: claimText!, role, names: rememberedNames() });
    } catch (e) {
      candidatesError = e instanceof Error ? e.message : String(e);
    }
  }
  $effect(() => { void role; void models; untrack(() => { candidate = ""; void loadCandidates(); }); });

  const offered = $derived(models.filter((m) => candidates?.some((c) => c.ref === m.ref && !c.problem)));
  const refused = $derived((candidates ?? []).filter((c) => c.problem));
  const candidateItem = $derived(models.find((m) => m.ref === candidate.split("#")[0]) ?? null);
  const candidateSelfHosted = $derived(Boolean(candidateItem && isSelfHosted(candidateItem)));
  let nameOpen = $state(false);
  $effect(() => {
    const item = candidateItem;
    untrack(() => {
      candidateName = item && isSelfHosted(item) ? prefillName(item) : "";
      nameOpen = Boolean(item && isSelfHosted(item) && !rememberedNames()[localModel(item)]);
    });
  });

  const neededProviders = $derived.by(() => {
    if (!claim) return [];
    const providers = new Set<string>();
    for (const r of [...Object.values(claim.setup.roles), claim.judge]) if (r && r.provider !== "self_hosted") providers.add(r.provider);
    if (candidateItem && !isSelfHosted(candidateItem)) providers.add(String(candidateItem.source));
    return [...providers];
  });
  const missingKeys = $derived(neededProviders.filter((p) => (app.runtime?.keys?.[p] ?? "missing") === "missing"));

  function declaredNames(): Record<string, string> {
    const names: Record<string, string> = {};
    for (const [name, spec] of [...selfHostedRoles, ...(judgeSelfHosted ? [["judge", judgeSelfHosted] as [string, ClaimRole]] : [])]) {
      const item = models.find((m) => m.ref === matches[name]);
      if (item) names[localModel(item)] = spec.model;
    }
    if (candidateItem && candidateSelfHosted) names[localModel(candidateItem)] = candidateName;
    return names;
  }

  const runReasons = $derived.by(() => {
    const reasons: string[] = [];
    if (!app.backend) return ["Engine loading (cached after the first visit)."];
    if (!claim) return [];
    for (const p of missingKeys) reasons.push(`Add ${p === "openai" ? "an OpenAI" : "an Anthropic"} key to run this.`);
    for (const [name] of [...selfHostedRoles, ...(judgeSelfHosted ? [["judge"]] : [])]) {
      if (!matches[name as string]) reasons.push(`Choose your model for ${name} (declared as ${name === "judge" ? judgeSelfHosted?.model : claim.setup.roles[name as string]?.model}).`);
    }
    for (const [name, spec] of Object.entries(claim.setup.roles)) {
      if (spec && spec.provider !== "self_hosted" && !missingKeys.includes(spec.provider)
          && !models.some((m) => m.ref === `${spec.provider}:${spec.model}`)) reasons.push(`${spec.model} (${name}) isn't available for your key.`);
    }
    if (candidateSelfHosted && nameProblem(candidateName)) reasons.push(nameProblem(candidateName));
    if (buildError) reasons.push(buildError);
    if (priced && !capSet) reasons.push("Set a spend limit above $0 to run this.");
    if (estimate?.unknown_prices?.length) reasons.push(`${estimate.unknown_prices.join(", ")} has no known price; strict budgets can't run it.`);
    return reasons;
  });

  function request(): ClaimExperimentRequest {
    const local: Record<string, string> = {};
    for (const [name] of selfHostedRoles) if (matches[name]) local[name] = matches[name];
    return {
      claim: claimText!, local, judge_local: judgeSelfHosted ? matches.judge || null : null,
      swap: role && candidate ? { role, candidate } : null, cap_usd: cap,
      gist_id: link?.kind === "gist" ? link.id : null, revision: link?.kind === "gist" ? link.revision : null,
      declared_names: declaredNames(),
    };
  }

  async function plan() {
    buildError = "";
    estimate = null;
    experiment = null;
    if (!app.backend || !claim || check?.state !== "ok" || missingKeys.length) return;
    if ([...selfHostedRoles.map(([n]) => n), ...(judgeSelfHosted ? ["judge"] : [])].some((n) => !matches[n])) return;
    if (candidateSelfHosted && nameProblem(candidateName)) return;
    try {
      // A placeholder limit for estimating: the engine refuses a priced run without one.
      const built = await app.backend.claimExperiment({ ...request(), cap_usd: 0 });
      estimate = await app.backend.estimate(built);
      experiment = built;
      if (!capTouched) cap = estimate.cost_usd > 0 ? Math.round(estimate.cost_usd * 1.5 * 10000) / 10000 : null;
    } catch (e) {
      buildError = e instanceof Error ? e.message : String(e);
    }
  }
  $effect(() => {
    void check; void role; void candidate; void candidateName; void matches; void missingKeys.length;
    untrack(() => void plan());
  });

  const unpricedRoles = $derived(claim ? Object.entries(claim.setup.roles).filter(([, r]) => r?.provider === "self_hosted").map(([n]) => n) : []);

  async function run() {
    if (!app.backend || !experiment || runReasons.length) return;
    try {
      const built = await app.backend.claimExperiment({ ...request(), cap_usd: capSet ? cap : null });
      const id = await app.backend.startRun({ experiment: built });
      for (const [local, name] of Object.entries(declaredNames())) rememberName(local, name);
      for (const [name, ref] of Object.entries(matches)) if (ref) rememberMatch(check!.claim_hash, name, ref);
      saveClaimRunNote(id, { claim: claimText!, ...(link?.kind === "gist" ? { gist_id: link.id, revision: link.revision } : {}) });
      running = id;
      result = null;
      progress = { ...initialProgress };
      app.backend.events(id, (event) => {
        progress = reduce(progress, event);
        if (event.type === "run_finished") void finish(id);
      });
    } catch (e) {
      buildError = e instanceof Error ? e.message : String(e);
    }
  }

  async function finish(id: string) {
    result = await app.backend!.bundle(id);
    queueMicrotask(() => resultHeading?.focus());
  }

  function declare(name: string, spec: ClaimRole) {
    const ref = declareRole[name];
    const item = models.find((m) => m.ref === ref);
    if (!item) return;
    rememberName(localModel(item), spec.model);
    matches = { ...matches, [name]: item.ref };
  }

  const statusWords: Record<ThreadRow["status"], string> = {
    counted: "counted", author: "author's own, not counted", superseded: "superseded by a later one", rejected: "rejected",
    edited: "edited", filtered: "other engine",
  };
  const localAppLink = $derived(typeof location === "undefined" ? "" : `http://127.0.0.1:8787/${location.hash}`);
</script>

{#if invalid && !claim}
  <p class="error" role="alert">This link doesn't contain a valid claim. {invalid !== "This link doesn't contain a valid claim." ? invalid : ""}</p>
  <p><a href="#/">Browse scenarios</a></p>
{:else if failure && !claimText}
  {#if failure.kind === "not_found"}
    <p class="error" role="alert">{failureText(failure)}</p>
    <p><a href="#/">Browse scenarios</a></p>
  {:else}
    <p class="note" role="status">{failureText(failure)} <button onclick={fetchClaim}>Retry</button></p>
  {/if}
{:else if !claimText}
  <p class="muted" role="status">Fetching claim…</p>
{:else}
  {#if edited && link?.kind === "gist"}
    <p class="note" role="status">This claim was edited after the link was shared. Showing the shared version.
      <a href={`#/claim/gist/${link.id}@${gist?.head_revision}`}>Show current version</a></p>
  {/if}
  <header class="claim-head">
    {#if claim}
      <h1 tabindex="-1" bind:this={heading}>Claim: {claim.scenario} v{claim.scenario_version} · {claim.tasks.length} tasks
        {#if selfHostedClaim}<span class="pill">self-hosted</span>{/if}</h1>
    {:else if preview}
      <h1 tabindex="-1" bind:this={heading}>Claim: {preview.scenario} v{preview.version} · {preview.tasks} tasks</h1>
    {:else}
      <h1 tabindex="-1" bind:this={heading}>Claim</h1>
    {/if}
    {#if gist?.owner}<p class="muted small">claimed by @{gist.owner} · <a href={gist.html_url} target="_blank" rel="noopener">gist</a></p>{/if}
    <div class="numbers" aria-live="polite">
      {#if claim || preview}
        {@const rate = claim?.result.pass_rate ?? preview!.passRate}
        {@const cost = claim?.result.cost_usd_per_task ?? preview!.costPerTask}
        <span>claimed {pct(rate)} · {unpricedRoles.length && cost === 0 ? NOT_PRICED : `${usd(cost)}/task`}{unpricedRoles.length && cost > 0 ? ` + ${NOT_PRICED} (${unpricedRoles.join(", ")})` : ""}</span>
        <span class="sep" aria-hidden="true">|</span>
        <span>
          {#if !claim}<span class="pill">checking…</span>
          {:else if link?.kind !== "gist"}no reproduction thread (link without a gist)
          {:else if !stats}<span class="muted">loading reproductions…</span>
          {:else if stats.people === 0}not yet reproduced
          {:else}reproduced by {stats.partial ? "at least " : ""}{stats.people} {stats.people === 1 ? "person" : "people"} · {pct(stats.rate)}{#if stats.low != null} [{pct(stats.low)}–{pct(stats.high)}]{/if}
          {/if}
          {#if stats?.partial} · based on the first {stats.loaded} of {stats.total} comments{/if}
          {#if stats?.removed} · {stats.removed} reproduction{stats.removed === 1 ? "" : "s"} referenced by later ones were removed{/if}
          {#if selfHostedClaim} · names self-declared{/if}
        </span>
      {/if}
    </div>
    {#if trustBars}<BarsCI bars={trustBars} label="Claimed and reproduced pass rate" />{/if}
    {#if stats?.above_interval && claim}<p class="note">The claimed {pct(claim.result.pass_rate)} is above the 95% interval of {stats.people} independent reproductions [{pct(stats.low)}–{pct(stats.high)}].</p>{/if}
    <p class="lead">Someone claims this model setup passes these tasks. Re-run it with your own keys, swap one model, and post your numbers.</p>
  </header>

  {#if claim && check}
    <div class="workspace">
      <section class="setup" aria-labelledby="setup-title">
        <h2 id="setup-title">Setup</h2>
        <table>
          <tbody>
            {#each Object.entries(claim.setup.roles) as [name, spec] (name)}
              {#if spec}
                <tr class:chosen={name === role}>
                  <th scope="row">{name}</th>
                  <td>{roleLabel(spec)}
                    {#if spec.provider === "self_hosted"}
                      {@const options = declaredAs(spec.model, models)}
                      <div class="here">
                        {#if options.length}
                          <label>here: <select bind:value={matches[name]} aria-label={`Your model for ${name}`}>
                            {#each options as m (m.ref)}<option value={m.ref}>{m.ref}</option>{/each}
                          </select></label>
                        {:else}
                          {@const own = models.filter(isSelfHosted)}
                          <div class="note">None of your models is declared as {spec.model}.
                            {#if own.length}
                              Use one of yours as {spec.model}:
                              <select bind:value={declareRole[name]} aria-label={`Declare one of your models as ${spec.model}`}>
                                <option value="">choose…</option>
                                {#each own as m (m.ref)}<option value={m.ref}>{m.ref}{rememberedNames()[localModel(m)] ? ` (was ${rememberedNames()[localModel(m)]})` : ""}</option>{/each}
                              </select>
                              <button onclick={() => declare(name, spec)} disabled={!declareRole[name]}>Use</button>
                            {:else if mode === "browser"}
                              Add an endpoint on <a href="#/models">Models</a> (endpoints need CORS to work here), or open this claim in the local app.
                            {:else}
                              Add or start one on <a href="#/models">Models</a>.
                            {/if}
                          </div>
                        {/if}
                      </div>
                    {/if}
                  </td>
                </tr>
              {/if}
            {/each}
            {#if claim.judge}<tr><th scope="row">judge</th><td>{roleLabel(claim.judge)}</td></tr>
            {:else if check.uses_judge}<tr><th scope="row">judge</th><td class="muted">none: graded by code checks only</td></tr>{/if}
          </tbody>
        </table>
        <p class="muted small">Params: {Object.entries(claim.setup.params ?? {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ") || "defaults"} ·
          control: {policyOf(claim.setup)} · seed {claim.seed} · {claim.repeats} repeat{claim.repeats === 1 ? "" : "s"}</p>
        {#if selfHostedClaim}<p class="muted small">Self-hosted: names are declared by people; serving may differ (quantization, context).</p>{/if}
      </section>

      <section class="beat" aria-labelledby="beat-title">
        <h2 id="beat-title">Beat this setup</h2>
        {#if check.state !== "ok"}
          <p class="note">{check.message}</p>
        {:else if running && !progress.finished}
          <RunProgress runId={running} {progress} />
        {:else}
          <label class="field">Swap one step
            <select bind:value={role}>
              <option value="">none: reproduce only</option>
              {#each check.swappable_roles ?? [] as r (r)}<option value={r}>{r}</option>{/each}
            </select>
          </label>
          {#if role}
            {#if candidatesError}<p class="note">{candidatesError} <button onclick={loadCandidates}>Retry</button></p>
            {:else if candidates === null}<select disabled aria-label="Candidate model"><option>loading models…</option></select>
            {:else if !offered.length}<p class="muted">No model you can use passes this claim's rules.</p>
            {:else}
              <ModelRefInput id="candidate" bind:value={candidate} options={offered} label="Candidate model" empty="choose a model…" thinkingWithModel />
            {/if}
            {#if refused.length}
              <details class="small"><summary>{refused.length} model{refused.length === 1 ? "" : "s"} not offered · why</summary>
                <ul>{#each refused as c (c.ref)}<li>{c.ref} · {c.problem}</li>{/each}</ul>
                {#each Object.entries(app.models?.unavailable ?? {}) as [source, why] (source)}<p class="muted">{source} couldn't be reached ({why}) · <a href="#/models">Models</a></p>{/each}
              </details>
            {/if}
            {#if candidateSelfHosted}
              {#if nameOpen}
                <label class="field">Compare as
                  <input bind:value={candidateName} aria-describedby="candidate-name-hint" />
                  <span id="candidate-name-hint" class="muted small" class:fail={Boolean(nameProblem(candidateName))}>{nameProblem(candidateName) || "lowercase letters, digits, . and -; up to 64"}</span>
                </label>
              {:else}
                <p class="small">compare as {candidateName} · <button class="link" onclick={() => (nameOpen = true)}>change</button></p>
              {/if}
            {/if}
          {/if}
          {#if missingKeys.length}
            <KeyPanel providers={missingKeys} heading={`Add ${missingKeys.map((p) => (p === "openai" ? "an OpenAI" : "an Anthropic")).join(" and ")} key to run this${estimate ? ` · est. ${usd(estimate.cost_usd)}` : ""} · the key stays in this ${mode === "local" ? "app" : "tab"}`} />
          {/if}
          {#if estimate}
            {#if priced}
              <label class="field">Spend limit (USD)
                <input type="number" min="0" step="0.01" bind:value={cap} oninput={() => (capTouched = true)} aria-describedby="limit-hint" />
              </label>
              <p id="limit-hint" class="muted small">Estimate {usd(estimate.cost_usd)}{estimate.needs_cap && estimate.cost_usd === 0 ? " plus a paid decision service the estimate doesn't cover" : ""}. The run stops at this limit; a stopped run can't be posted.
                {#if unpricedRoles.length || candidateSelfHosted} Covers OpenAI/Anthropic only; {[...unpricedRoles, ...(candidateSelfHosted ? [role] : [])].join(", ")} isn't priced and isn't limited.{/if}</p>
              {#if cap != null && cap < estimate.cost_usd}<p class="note">The limit is below the estimate; the run may stop early and then can't be posted.</p>{/if}
            {:else}
              <p class="muted small">Nothing in this run is priced, so there is no spend limit.</p>
            {/if}
          {/if}
          <button class="primary" onclick={run} disabled={!experiment || runReasons.length > 0} aria-describedby="run-reasons">
            {role && candidate ? "Run claimed setup + variant" : "Run claimed setup"}</button>
          {#if runReasons.length}<div id="run-reasons" class="small reasons">{#each runReasons as reason}<p>{reason}</p>{/each}</div>{/if}
          {#if mode === "browser" && localAppLink}
            <p class="muted small local-link"><a href={localAppLink}>Open in local app</a> (for local models). Start it with
              <code>uv run arena ui --port 8787</code> first, then click.</p>
          {/if}
        {/if}
      </section>
    </div>
  {:else if preview}
    <section class="setup">
      <h2>Setup</h2>
      <table><tbody>{#each preview.roles as line (line.role)}<tr><th scope="row">{line.role}</th><td>{line.model}</td></tr>{/each}</tbody></table>
      <p class="muted small" aria-live="polite">{app.backend ? "checking…" : "Engine loading (cached after the first visit)."}</p>
    </section>
  {/if}

  {#if running && progress.finished}
    <section aria-labelledby="result-title">
      <h2 id="result-title" tabindex="-1" bind:this={resultHeading}>Your result</h2>
      {#if stopReason(progress)}<p class="note">This run stopped early ({stopReason(progress)}), so it can't be posted.</p>{/if}
      {#if result}
        {#if result.summary.replacements?.length}<ReplacementEffects effects={result.summary.replacements} />{/if}
        <ClaimBand runId={running} bundle={result} onposted={reloadThread} />
        <p class="muted small"><a href={`#/runs/${encodeURIComponent(running)}`}>Open full run</a></p>
      {:else}<p class="muted">Loading the result…</p>{/if}
    </section>
  {/if}

  {#if link?.kind === "gist" && claim}
    <section aria-labelledby="thread-title">
      <h2 id="thread-title" aria-live="polite">Reproductions ({stats?.rows.length ?? "…"})</h2>
      {#if threadFailure}<p class="note">{failureText(threadFailure)} <button onclick={loadThread}>Retry</button></p>{/if}
      {#if threadError}<p class="error" role="alert">The reproductions couldn't be tallied: {threadError}</p>{/if}
      {#if stats}
        <label class="small">Engine <select bind:value={engineFilter}><option value="">all</option><option value="pages">pages</option><option value="local">local</option></select></label>
        {#if !stats.rows.length}
          <p class="muted">Not reproduced yet. Be the first{#if estimate}: re-running {estimate.cost_usd > 0 ? `costs ≈ ${usd(estimate.cost_usd)}` : priced ? "uses a paid decision service" : `uses your own models (${NOT_PRICED})`}{/if}.</p>
        {/if}
        {#each stats.rows as row (row.comment_id)}
          <div class="card repro">
            <span class="pill" class:good={row.status === "counted"} class:bad={row.status === "rejected"}>{statusWords[row.status]}</span>
            <span>@{row.user}</span> <span class="muted small">{row.created_at.slice(0, 10)}</span>
            {#if row.engine}<span class="pill">{row.engine}</span>{/if}
            <span>{row.baseline_passed}/{row.baseline_trials} · {usd(row.baseline_cost_usd_per_task)}</span>
            {#if row.variant_role}<span>{row.variant_role} → {row.variant_model}: {row.variant_passed}/{row.baseline_trials}</span>{/if}
            {#if row.reason && row.status !== "counted"}<p class="small muted">{row.reason}</p>{/if}
          </div>
        {/each}
        {#if stats.hidden}<p class="muted small">+{stats.hidden} comment{stats.hidden === 1 ? "" : "s"} without a reproduction</p>{/if}
        <p class="muted small">The gist's owner can delete comments; a deletion before anyone else posts can't be detected.</p>
      {/if}
    </section>
  {/if}
{/if}

<style>
  .claim-head h1 { margin-bottom: 4px; overflow-wrap: anywhere; }
  .numbers { display: flex; gap: 12px; flex-wrap: wrap; font-size: 17px; font-variant-numeric: tabular-nums; margin: 8px 0; }
  .sep { color: var(--text-muted, var(--text-secondary)); }
  .workspace { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 20px; margin: 16px 0; }
  .setup, .beat { background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 16px; min-width: 0; }
  .setup table { width: 100%; border-collapse: collapse; }
  .setup th, .setup td { text-align: left; padding: 6px 4px; border-bottom: 1px solid var(--border); vertical-align: top; overflow-wrap: anywhere; }
  .setup tr.chosen { background: var(--surface-2); }
  .here { margin-top: 4px; font-size: 13px; }
  .field { display: grid; gap: 4px; margin: 8px 0; }
  .reasons p { margin: 4px 0; color: var(--text-secondary); }
  .repro { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; margin: 6px 0; padding: 8px 12px; }
  .pill.good { color: var(--good); border-color: var(--good); }
  .pill.bad { color: var(--critical); border-color: var(--critical); }
  .pill { overflow-wrap: anywhere; }
  button, select, input { min-height: 36px; }
  @media (max-width: 640px) {
    .workspace { grid-template-columns: 1fr; }
    button, select, input { min-height: 44px; }
  }
  @media (hover: none) { .local-link { display: none; } }
</style>
