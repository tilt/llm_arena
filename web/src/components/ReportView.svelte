<script lang="ts">
  import type { RunBundle, ScenarioManifest } from "../lib/contracts";
  import { num, pct, usd } from "../lib/format";
  import { bars, passRateMatrix, ratings, sections, stepMatrix, trials } from "../lib/report";
  import BarsCI from "./BarsCI.svelte";
  import Heatmap from "./Heatmap.svelte";
  import TraceDetails from "./TraceDetails.svelte";

  let { bundle, manifests = [] }: { bundle: RunBundle; manifests?: ScenarioManifest[] } = $props();

  const scenarioSections = $derived(sections(bundle));
  const overview = $derived(passRateMatrix(bundle));
  const rated = $derived(ratings(bundle));
  const rows = $derived(trials(bundle));
  const wikiFor = (id: string) => manifests.find((m) => m.id === id)?.wiki ?? [];

  let filterScenario = $state("");
  let filterConfig = $state("");
  let filterOutcome = $state("");
  const visible = $derived(
    rows.filter((t) => (!filterScenario || t.scenario === filterScenario) && (!filterConfig || t.config === filterConfig)
      && (!filterOutcome || (filterOutcome === "pass") === t.passed)),
  );
  const totals = $derived({
    trials: rows.length,
    passed: rows.filter((t) => t.passed).length,
    errors: rows.filter((t) => t.status !== "ok").length,
    tokens: rows.reduce((sum, t) => sum + t.tokens, 0),
    cost: bundle.trials.reduce((sum, t) => sum + Number(t.cost_usd ?? 0), 0),
    judge: bundle.trials.reduce((sum, t) => sum + Number(t.judge_cost_usd ?? 0), 0),
  });
</script>

<section class="tiles">
  <div class="card tile"><div class="k">Trials</div><div class="v">{totals.trials}</div><div class="s">{totals.errors} errors/timeouts</div></div>
  <div class="card tile"><div class="k">Pass rate</div><div class="v">{pct(totals.trials ? totals.passed / totals.trials : null)}</div><div class="s">all scenarios and configs</div></div>
  <div class="card tile"><div class="k">Tokens</div><div class="v">{totals.tokens.toLocaleString("en-US")}</div><div class="s">prompt + completion</div></div>
  <div class="card tile"><div class="k">Model cost</div><div class="v">{usd(totals.cost)}</div><div class="s">judge: {usd(totals.judge)}</div></div>
  <div class="card tile"><div class="k">Arena battles</div><div class="v">{bundle.battles.length}</div><div class="s">pairwise, position-swapped</div></div>
</section>

<h2>Overview</h2>
<p class="lead">
  Pass rate per configuration and scenario. A trial passes only when every pass criterion of its scenario holds,
  quality and safety checks together.
</p>
<div class="card"><Heatmap matrix={overview} format={(v) => pct(v)} label="Pass rate by configuration and scenario" /></div>

{#each scenarioSections as section (section.scenario)}
  <h2 id={`sc-${section.scenario}`}>{section.scenario} <span class="pill">{section.pattern}</span></h2>
  {#if wikiFor(section.scenario).length}
    <p class="muted wiki">Read up:
      {#each wikiFor(section.scenario) as link (link.url)}<a href={link.url} target="_blank" rel="noopener">{link.title}</a>{/each}
    </p>
  {/if}
  <div class="card report-block"><BarsCI bars={bars(section)} label={`Pass rate with 95% confidence interval for ${section.scenario}`} /></div>
  <div class="card table-wrap report-block">
    <table>
      <thead><tr><th>Config</th><th>Roles</th><th class="n">Pass rate [95% CI]</th><th class="n">pass^k</th><th class="n">pass@k</th>
        <th class="n">Tasks×k</th><th class="n">Tokens/trial</th><th class="n">$/trial</th><th class="n">p50 / p95 s</th><th class="n">Errors</th></tr></thead>
      <tbody>
        {#each section.configs as c (c.config)}
          <tr>
            <td><strong>{c.config}</strong></td>
            <td>{#each Object.entries(c.roles) as [role, model] (role)}<span class="pill">{role}: {model}</span>{/each}</td>
            <td class="n">{pct(c.pass_rate)} <span class="muted">[{pct(c.ci_low)}–{pct(c.ci_high)}]</span></td>
            <td class="n">{pct(c.pass_hat_k)}</td><td class="n">{pct(c.pass_at_k)}</td>
            <td class="n">{c.tasks}×{c.repeats}</td><td class="n">{num(c.mean_tokens, 0)}</td><td class="n">{usd(c.mean_cost_usd)}</td>
            <td class="n">{num(c.latency_p50_s, 1)} / {num(c.latency_p95_s, 1)}</td>
            <td class="n">{#if c.errors}<span class="fail">{c.errors}</span>{:else}0{/if}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  {#if section.e2eMetrics.length}
    <h3>End-to-end metrics</h3>
    <div class="card table-wrap report-block">
      <table>
        <thead><tr><th>Config</th>{#each section.e2eMetrics as m (m)}<th class="n">{m}</th>{/each}</tr></thead>
        <tbody>{#each section.configs as c (c.config)}<tr><td>{c.config}</td>{#each section.e2eMetrics as m (m)}<td class="n">{num(c.e2e_means?.[m])}</td>{/each}</tr>{/each}</tbody>
      </table>
    </div>
  {/if}

  {#if section.stepMetrics.length}
    <h3>Step-level metrics</h3>
    <p class="lead">Each pipeline step is scored from the trace, so you can see which step is responsible when a result gets worse.</p>
    {#if section.rateMetrics.length}
      <div class="card report-block"><Heatmap matrix={stepMatrix(section)} format={(v) => num(v)} label={`Step metrics for ${section.scenario}`} /></div>
    {/if}
    <div class="card table-wrap report-block">
      <table>
        <thead><tr><th>Config</th>{#each [...section.stepMetrics, ...section.derivedMetrics] as m (m)}<th class="n">{m}</th>{/each}</tr></thead>
        <tbody>
          {#each section.configs as c (c.config)}
            <tr><td>{c.config}</td>
              {#each section.stepMetrics as m (m)}<td class="n">{num(c.step_means?.[m])}</td>{/each}
              {#each section.derivedMetrics as m (m)}<td class="n">{num(c.derived?.[m])}</td>{/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}

  {#if section.tests.length}
    <h3>Is the leader significantly better?</h3>
    <div class="card table-wrap report-block">
      <table>
        <thead><tr><th>Leader</th><th>vs.</th><th class="n">Δ pass rate</th><th class="n">p (paired permutation)</th><th class="n">Tasks</th></tr></thead>
        <tbody>
          {#each section.tests as t (t.other)}
            <tr><td>{t.best}</td><td>{t.other}</td><td class="n">{pct(t.difference)}</td>
              <td class="n" class:pass={t.p_value < 0.05}>{num(t.p_value, 3)}</td><td class="n">{t.tasks}</td></tr>
          {/each}
        </tbody>
      </table>
      {#if section.tests.some((t) => t.tasks < 20)}
        <p class="note">Fewer than 20 shared tasks: treat the differences as indicative only. Add tasks or repeats for firmer conclusions.</p>
      {/if}
    </div>
  {/if}
{/each}

{#if rated.length}
  <h2>Arena ratings</h2>
  <p class="lead">Bradley–Terry ratings (Elo scale, centred on 1000) from pairwise judge battles, each judged twice with the positions swapped.</p>
  <div class="card table-wrap report-block">
    <table>
      <thead><tr><th>Scope</th><th>Ranking</th></tr></thead>
      <tbody>{#each rated as r (r.scope)}<tr><td>{r.scope}</td><td>{#each r.ranking as [cfg, rating] (cfg)}<span class="pill">{cfg} {num(rating, 0)}</span>{/each}</td></tr>{/each}</tbody>
    </table>
  </div>
{/if}

<h2>Trace explorer</h2>
<div class="filters">
  <select bind:value={filterScenario} aria-label="Filter by scenario"><option value="">All scenarios</option>
    {#each overview.columns as s (s)}<option>{s}</option>{/each}</select>
  <select bind:value={filterConfig} aria-label="Filter by config"><option value="">All configs</option>
    {#each overview.rows as c (c)}<option>{c}</option>{/each}</select>
  <select bind:value={filterOutcome} aria-label="Filter by outcome"><option value="">All outcomes</option><option value="pass">Passed</option><option value="fail">Failed</option></select>
  <span class="muted">{visible.length} of {rows.length}</span>
</div>
<div class="card">
  {#each visible.slice(0, 300) as t (t.trial_id)}
    <TraceDetails trial={t} scores={bundle.scores.filter((s) => s.trial_id === t.trial_id)} trace={bundle.traces[t.trial_id]} />
  {/each}
</div>

<style>
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-top: 16px; }
  .tile .k { color: var(--text-secondary); font-size: 13px; }
  .tile .v { font-size: 26px; font-weight: 600; }
  .tile .s { color: var(--text-muted); font-size: 12px; }
  :global(.report-block) + :global(.report-block) { margin-top: 12px; }
  .wiki a { margin-left: 8px; }
  .filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; }
</style>
