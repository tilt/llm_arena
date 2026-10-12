<script lang="ts">
  // The public claims board (docs/designs/claims-board.md §9). It reads one static board.json and never needs the
  // in-browser engine, so App renders it outside the engine gate (eng D2).
  import { app } from "../lib/app.svelte";
  import {
    GROUPS, OVERALL, PAGES_BOARD, SUBMIT_FORM, answerLine, claimHref, defaultFeed, defaultTab, entryLabel, gapText,
    interval, isStale, linkable, loadBoard, nextUpdate, noteText, overallOf, rowsOf, saveFeed, scenarioOf, setupText,
    storedFeed, tierText, type BoardLoad, type Feed, type Group, type Row,
  } from "../lib/board";
  import { pct, usd } from "../lib/format";
  import { roleLinesOf } from "../lib/leaderboard";
  import IntervalStrip from "../components/IntervalStrip.svelte";

  let { tab }: { tab?: string } = $props();

  let load = $state<BoardLoad | null>(null);
  let group = $state<Group>("all");
  let highlighted = $state<string | null>(null);
  let chosen = $state<Record<string, Feed>>({});
  const now = new Date();

  $effect(() => {
    void loadBoard(import.meta.env.BASE_URL).then((value) => (load = value));
  });

  const board = $derived(load?.state === "ok" ? load.board : null);
  const current = $derived(board ? (tab && (tab === OVERALL || scenarioOf(board, tab)) ? tab : defaultTab(board)) : "");
  const unknownTab = $derived(Boolean(board && tab && tab !== current));
  const scenario = $derived(board && current !== OVERALL ? scenarioOf(board, current) : undefined);
  const feed = $derived<Feed>(board ? chosen[current] ?? storedFeed(current) ?? defaultFeed(board, current) : "reproduced");
  const rows = $derived(scenario ? rowsOf(scenario, feed) : []);
  const entries = $derived(board ? overallOf(board, feed, group) : []);
  const countLine = $derived(current === OVERALL
    ? `Showing ${entries.length} model${entries.length === 1 ? "" : "s"}`
    : `Showing ${rows.length} ${feed === "reproduced" ? "reproduced " : ""}setup${rows.length === 1 ? "" : "s"}`);

  function setFeed(value: Feed): void {
    chosen = { ...chosen, [current]: value };
    saveFeed(current, value);
  }

  // ---- the chart: pass rate against cost per task (design 1A: below the table, the same rows) ----------------------
  const W = 640, H = 240, PAD = 36;
  const costs = $derived(rows.map((r) => Math.max(r.cost_usd_per_task, 1e-5)));
  const lo = $derived(Math.log10(Math.min(...costs, 1e-3)) - 0.1);
  const hi = $derived(Math.log10(Math.max(...costs, 1e-2)) + 0.1);
  const cx = (row: Row) => PAD + ((Math.log10(Math.max(row.cost_usd_per_task, 1e-5)) - lo) / (hi - lo)) * (W - 2 * PAD);
  const cy = (v: number) => H - PAD - v * (H - 2 * PAD);
  const radius = (row: Row) => 4 + 2.5 * Math.sqrt(row.people);
  const ticks = $derived([lo, (lo + hi) / 2, hi].map((v) => ({ v, label: usd(10 ** v) })));
</script>

<section class="board">
  <header class="top">
    <h1>Claims board</h1>
    <details class="submit">
      <summary class="button">Submit a claim</summary>
      <div class="steps">
        <ol>
          <li>Run a scenario (<a href="#/">Scenarios</a>).</li>
          <li>On the run page, choose <b>Share as claim</b>.</li>
          <li>On the claim page, choose <b>Submit to board</b>.</li>
        </ol>
        <p class="muted small">Already have a claim gist? <a href={SUBMIT_FORM} target="_blank" rel="noopener">Open the submission form</a>.</p>
      </div>
    </details>
  </header>

  {#if load === null}
    <p class="muted" role="status">Loading the board…</p>
  {:else if load.state === "missing"}
    {#if app.mode === "local"}
      <p class="note">The claims board is built on the public site. <a href={PAGES_BOARD} target="_blank" rel="noopener">Open the board</a>.</p>
    {:else}
      <p class="note">The board isn't built yet. Claims still open from their own links.</p>
    {/if}
  {:else if load.state === "outdated"}
    <p class="note">This page is out of date. <button class="linklike" onclick={() => location.reload()}>Reload</button> to see the current board.</p>
  {:else if load.state === "error"}
    <p class="note" role="alert">{load.message}</p>
  {:else if board}
    <p class="lead">
      {#if scenario}{answerLine(scenario)}{:else}Models across all scenarios, by role. Numbers are associations from the setups they appear in.{/if}
    </p>
    {#if unknownTab}<p class="note">No claims for {tab} on the board.</p>{/if}
    {#if isStale(board, now)}<p class="note">Last updated {board.built_at.slice(0, 16).replace("T", " ")} UTC; numbers may be behind.</p>{/if}

    <nav class="tabs" aria-label="Board tabs">
      <a href="#/board/overall" aria-current={current === OVERALL ? "page" : undefined}>Overall</a>
      {#each board.scenarios as s (s.scenario)}
        <a href={`#/board/${encodeURIComponent(s.scenario)}`} aria-current={current === s.scenario ? "page" : undefined}>{s.scenario} v{s.version}</a>
      {/each}
    </nav>

    <div class="controls">
      <h2>{current === OVERALL ? "Models by role" : "Ranked setups"}</h2>
      <div class="pills" role="radiogroup" aria-label="Which claims to include">
        {#each [["reproduced", "Reproduced only"], ["merged", "Include unreproduced"]] as [value, label] (value)}
          <label class="pill" class:on={feed === value}>
            <input type="radio" name="feed" value={value} checked={feed === value} onchange={() => setFeed(value as Feed)} />{label}
          </label>
        {/each}
      </div>
    </div>
    <p class="sr-only" aria-live="polite">{countLine}</p>

    {#if current === OVERALL}
      <div class="pills groups" role="radiogroup" aria-label="Role group">
        {#each GROUPS as g (g.id)}
          <label class="pill" class:on={group === g.id}>
            <input type="radio" name="group" value={g.id} checked={group === g.id} onchange={() => (group = g.id)} />
            <span class="dot" style={`background: var(${g.token})`}></span>{g.label}
          </label>
        {/each}
      </div>
      {#if entries.length === 0}
        <p class="muted">No reproduced claims yet. Switch to <b>Include unreproduced</b> to see claimed setups.</p>
      {:else}
        <table class="overall">
          <caption class="sr-only">Models ranked by their mean gap to the best setup in each scenario</caption>
          <thead><tr><th scope="col">#</th><th scope="col">Model</th><th scope="col">Standing</th><th scope="col">Evidence</th></tr></thead>
          <tbody>
            {#each entries as entry, i (`${entry.provider}:${entry.model}:${entry.reasoning_effort}:${entry.tool_mode}`)}
              <tr>
                <td class="num">{i + 1}</td>
                <td><span class="model">{entryLabel(entry)}</span>{#if entry.provider === "self_hosted"} <span class="muted small">(self-declared)</span>{/if}</td>
                <td><span class="num">{gapText(entry)}</span> <span class="muted small">· raw average {pct(entry.raw)}</span></td>
                <td class="appearance">appears in {entry.setups} setup{entry.setups === 1 ? "" : "s"} across {entry.scenarios} scenario{entry.scenarios === 1 ? "" : "s"}{#if entry.only_claim} · {entry.only_claim} only claim in its scenario{/if}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    {:else if scenario}
      {#if rows.length === 0}
        <p class="muted">No claim here has a reproduction yet. Reproduce one below{#if scenario.unreproduced[0]}, about {usd(scenario.unreproduced[0].reproduce_usd)} each{/if}.</p>
      {:else}
        <!-- Explicit roles: the phone layout's grid rows would otherwise drop the table's semantics. -->
        <!-- svelte-ignore a11y_no_redundant_roles (the phone grid drops implicit table roles) -->
        <table class="ranked" role="table">
          <caption class="sr-only">Setups for {scenario.scenario} ranked by the low end of their pass-rate interval</caption>
          <thead>
            <!-- svelte-ignore a11y_no_redundant_roles (the phone grid drops implicit table roles) -->
            <tr role="row"><th scope="col">#</th><th scope="col">Setup</th><th scope="col">Pass rate</th><th scope="col" class="wide">Steps that worked</th>
              <th scope="col">Confidence</th><th scope="col" class="wide">Cost/task</th><th scope="col" class="wide"><span class="sr-only">Action</span></th></tr>
          </thead>
          <tbody>
            {#each rows as row, i (row.claim_hash)}
              <!-- svelte-ignore a11y_no_redundant_roles (the phone grid drops implicit table roles) -->
              <tr role="row" class:lit={highlighted === row.claim_hash} onmouseenter={() => (highlighted = row.claim_hash)} onmouseleave={() => (highlighted = null)}
                  onfocusin={() => (highlighted = row.claim_hash)} onfocusout={() => (highlighted = null)}>
                <td role="cell" class="num rank">{i + 1}</td>
                <td role="cell" class="setup">
                  {#each roleLinesOf({ roles: row.roles }) as line (line.role)}<span class="pill chip">{line.role} · {line.model}</span>{/each}
                </td>
                <td role="cell" class="rate"><IntervalStrip low={row.low} rate={row.rate} high={row.high} /> <span class="num">{interval(row)}</span> <span class="muted small">· {row.tasks} tasks</span></td>
                <td role="cell" class="wide">{@render steps(row)}</td>
                <td role="cell"><span class={`pill tier ${row.tier}`}>{tierText(row)}</span>
                  {#if row.reproducers.length}<span class="sr-only">by {row.reproducers.join(", ")}</span>{/if}</td>
                <td role="cell" class="wide num">{usd(row.cost_usd_per_task)}{#if row.cost_source === "reproduced"} <span class="muted small">reproduced</span>{/if}</td>
                <td role="cell" class="wide">{@render beat(row)}</td>
                <td role="cell" class="phone">
                  <details><summary>Details</summary>{@render steps(row)}<p class="num">{usd(row.cost_usd_per_task)} per task</p>{@render beat(row)}</details>
                </td>
              </tr>
              {#each row.notes as note (note.kind)}
                <!-- svelte-ignore a11y_no_redundant_roles (the phone grid drops implicit table roles) -->
                <tr class="noterow" role="row"><td role="cell" colspan="7"><p class="note">{noteText(note)}</p></td></tr>
              {/each}
            {/each}
          </tbody>
        </table>
      {/if}

      {#if feed === "reproduced" && scenario.unreproduced.length}
        <h2>Waiting for a first reproduction ({scenario.unreproduced.length})</h2>
        <ul class="waiting">
          {#each scenario.unreproduced as row (row.claim_hash)}
            <li><span>{setupText(row)}</span> <span class="num">{pct(row.claimed_rate)} claimed</span>
              {#if linkable(row)}<a href={claimHref(row)}>Be the first to reproduce, about {usd(row.reproduce_usd)}</a>{/if}</li>
          {/each}
        </ul>
      {/if}

      {#if rows.length >= 2}
        <h2>Pass rate vs cost per task</h2>
        <svg class="chart" viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
          {#each [0, 0.5, 1] as v (v)}<line class="grid" x1={PAD} x2={W - PAD} y1={cy(v)} y2={cy(v)} /><text x="4" y={cy(v) + 4}>{pct(v)}</text>{/each}
          {#each ticks as t (t.v)}<text x={PAD + ((t.v - lo) / (hi - lo)) * (W - 2 * PAD) - 14} y={H - 10}>{t.label}</text>{/each}
          {#each rows as row (row.claim_hash)}
            <g class:dim={highlighted !== null && highlighted !== row.claim_hash} class:lit={highlighted === row.claim_hash}
               role="presentation" onmouseenter={() => (highlighted = row.claim_hash)} onmouseleave={() => (highlighted = null)}>
              <line class="bar" x1={cx(row)} x2={cx(row)} y1={cy(row.low)} y2={cy(row.high)} />
              <circle class={`dotc ${row.tier}`} cx={cx(row)} cy={cy(row.rate)} r={radius(row)} />
            </g>
          {/each}
        </svg>
        <p class="sr-only">Chart of the same {rows.length} claims: pass rate against cost per task. The table above lists every value.</p>
      {/if}

      {#if scenario.older.length}
        <details class="older"><summary>Older scenario versions ({scenario.older.length})</summary>
          <ul>{#each scenario.older as row (row.claim_hash)}<li>{setupText(row)} · v{row.scenario_version} · {pct(row.claimed_rate)} claimed</li>{/each}</ul>
        </details>
      {/if}
    {/if}

    {#if board.delisted.length}
      <details class="older"><summary>Delisted ({board.delisted.length})</summary>
        <ul>{#each board.delisted as d (d.claim_hash)}<li>{d.scenario}: delisted: {d.reason}</li>{/each}</ul>
      </details>
    {/if}

    <footer class="muted small">
      <p>Ranked by the low end of each task-level interval, then by steps. Reproduced numbers replace claimed ones.</p>
      <p>What this can't catch: reproductions are self-reported (one person with several accounts can inflate a claim);
        a reproduction deleted before the board's next update; comments beyond the first 300.</p>
      <p>Updated {board.built_at.slice(0, 16).replace("T", " ")} UTC · next update about {nextUpdate(board, now).toISOString().slice(11, 16)} UTC
        · {board.claims} claims, {board.reproductions} reproductions recorded.</p>
    </footer>
  {/if}
</section>

{#snippet steps(row: Row)}
  {#if row.criteria}
    <ul class="bars">
      {#each Object.entries(row.criteria) as [name, c] (name)}
        <li><span class="track"><span class="fill" style={`width:${(c.passed / c.graded) * 100}%`}></span></span> {name} {pct(c.passed / c.graded)}</li>
      {/each}
    </ul>
  {:else}<span class="muted small">steps {pct(row.step_credit)}</span>{/if}
{/snippet}

{#snippet beat(row: Row)}
  {#if linkable(row)}<a class="button beat" href={claimHref(row)}>Beat this</a>{:else}<span class="muted small">claim page unavailable</span>{/if}
{/snippet}

<style>
  .board { max-width: 1180px; }
  .top { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
  .submit { position: relative; }
  .submit summary { list-style: none; cursor: pointer; }
  .submit .steps { position: absolute; right: 0; z-index: 2; width: min(360px, 90vw); background: var(--surface-1);
    border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 16px; }
  .button { display: inline-flex; align-items: center; min-height: 32px; padding: 0 12px; border-radius: 8px;
    background: var(--surface-2); color: var(--text-primary); text-decoration: none; font-size: 14px; }
  .linklike { background: none; border: 0; padding: 0; color: var(--accent-text); text-decoration: underline; cursor: pointer; font: inherit; }
  .tabs { display: flex; gap: 16px; flex-wrap: wrap; border-bottom: 1px solid var(--border); margin: 8px 0 16px; }
  .tabs a { padding: 8px 0; color: var(--text-secondary); text-decoration: none; border-bottom: 2px solid transparent; }
  .tabs a[aria-current="page"] { color: var(--text-primary); border-bottom-color: var(--accent); font-weight: 600; }
  .controls { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
  .controls h2 { margin: 8px 0; }
  .pills label { cursor: pointer; }
  .pills input { position: absolute; opacity: 0; width: 1px; height: 1px; }
  .pills label:has(input:focus-visible) { outline: 2px solid var(--accent); outline-offset: 2px; }
  .groups { margin: 8px 0 12px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: 1px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 10px 12px 10px 0; border-bottom: 1px solid var(--border); vertical-align: middle; }
  th { color: var(--text-secondary); font-size: 13px; font-weight: 500; }
  .num { font-variant-numeric: tabular-nums; }
  .chip { margin: 1px 4px 1px 0; }
  .tier.claimed { background: transparent; border: 1px solid var(--axis); }
  .tier.reproduced { background: var(--seq-1); color: var(--ink-on-low); }
  .tier.verified { background: var(--seq-5); color: var(--ink-on-high); }
  tr.lit td { background: var(--surface-2); }
  .noterow td { border-bottom: 0; padding-top: 0; }
  .bars { list-style: none; margin: 0; padding: 0; font-size: 12px; color: var(--text-secondary); }
  .bars .track { display: inline-block; width: 60px; height: 6px; background: var(--surface-3); vertical-align: 1px; }
  .bars .fill { display: block; height: 6px; background: var(--seq-4); }
  .appearance { color: var(--text-muted); }
  .waiting { padding-left: 18px; }
  .waiting li { margin: 6px 0; }
  .chart { width: 100%; height: auto; max-width: 760px; }
  .chart text { font-size: 11px; fill: var(--text-muted); }
  .chart .grid { stroke: var(--grid); }
  .chart .bar { stroke: var(--axis); stroke-width: 1.5; }
  .chart .dotc.claimed { fill: transparent; stroke: var(--seq-3); stroke-width: 1.5; }
  .chart .dotc.reproduced { fill: var(--seq-1); }
  .chart .dotc.verified { fill: var(--seq-5); }
  .chart g.dim { opacity: 0.3; }
  .chart g.lit .dotc { stroke: var(--text-primary); stroke-width: 2; }
  .older { margin-top: 24px; }
  footer { margin-top: 32px; }
  .phone { display: none; }
  .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  @media (pointer: coarse) { .pills label, .button, .tabs a { min-height: 44px; display: inline-flex; align-items: center; } }
  @media (max-width: 640px) {
    .ranked thead { display: none; }
    .ranked tr { display: grid; grid-template-columns: auto 1fr; gap: 4px 8px; padding: 8px 0; border-bottom: 1px solid var(--border); }
    .ranked td { border: 0; padding: 0; }
    .ranked td.rank { grid-row: span 2; }
    .ranked td.wide { display: none; }
    .ranked td.phone { display: block; grid-column: 1 / -1; }
    .ranked .noterow { display: block; border: 0; }
    .phone .beat { width: 100%; justify-content: center; min-height: 44px; margin-top: 8px; }
  }
</style>
