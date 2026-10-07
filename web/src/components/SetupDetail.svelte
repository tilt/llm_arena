<script lang="ts">
  import { tick } from "svelte";
  import { app } from "../lib/app.svelte";
  import type { LeaderboardEntry, RunBundle, ScenarioManifest, TrialResult } from "../lib/contracts";
  import { pct } from "../lib/format";
  import { newest } from "../lib/latest";
  import { roleLines, setupPolicy } from "../lib/leaderboard";
  import { activeRuns, refreshRuns } from "../lib/runs.svelte";
  import RenameForm from "./RenameForm.svelte";

  // One leaderboard entry opened up: what it ran, how each task went (every cell opens that trial's step
  // inspector), and the runs it comes from.
  let {
    entry, manifest, onuse, onrenamed = () => undefined,
  }: { entry: LeaderboardEntry; manifest?: ScenarioManifest; onuse: () => void; onrenamed?: () => void } = $props();

  // Renaming one of the entry's runs: the form opens below the runs, for the run whose button was pressed.
  let renameRun = $state("");
  let renameBundle = $state<RunBundle | null>(null);
  let renameError = $state("");
  let renameLoading = $state(false);
  let renamedRun = $state("");
  let runList = $state<HTMLElement | null>(null);
  const beginLoad = newest();

  const tasks = $derived([...new Set((entry.results ?? []).map((r) => r.task_id))]);
  const byTask = $derived(Object.fromEntries(tasks.map((t) => [t, (entry.results ?? []).filter((r) => r.task_id === t)])));
  const params = $derived(Object.entries((entry.setup.params ?? {}) as Record<string, unknown>));
  const running = $derived(new Set(activeRuns().map((r) => r.run_id)));
  const inspect = (runId: string, trialId: string) => `#/runs/${encodeURIComponent(runId)}/trial/${encodeURIComponent(trialId)}`;
  const errors = $derived((entry.results ?? []).filter((r) => r.status !== "ok").length);
  const kindOf = (role: string) => manifest?.roles.find((r) => r.name === role)?.kind ?? "";
  // A failed trial that did part of the work: its cell fills from the bottom by its partial credit.
  const partial = (r: TrialResult) => (!r.passed && r.status === "ok" && r.credit != null ? r.credit : null);
  const partialFill = (r: TrialResult) => {
    const credit = partial(r);
    return credit ? `--credit:${Math.round(credit * 100)}%` : undefined;
  };
  const partialNote = (r: TrialResult) => {
    const credit = partial(r);
    return credit == null ? "" : ` · ${pct(credit)} of checks met`;
  };

  async function startRename(run: string) {
    if (!app.backend) return;
    // Only the newest request may fill the form: an older bundle arriving late would rename the wrong run.
    const current = beginLoad();
    renameRun = run;
    renameBundle = null;
    renameError = "";
    renamedRun = "";
    renameLoading = true;
    try {
      const bundle = await app.backend.bundle(run);
      if (current()) renameBundle = bundle;
    } catch (e) {
      if (current()) renameError = e instanceof Error ? e.message : String(e);
    } finally {
      if (current()) renameLoading = false;
    }
  }
  async function closeRename(saved: boolean) {
    const run = renameRun;
    beginLoad(); // a load still in flight no longer applies
    renameRun = "";
    renameBundle = null;
    renameError = "";
    renameLoading = false;
    await tick(); // the run's Rename button is enabled again
    runList?.querySelector<HTMLElement>(`[data-run="${CSS.escape(run)}"]`)?.focus();
    if (!saved) return;
    renamedRun = run;
    onrenamed();
    void refreshRuns();
  }
</script>

<div class="detail">
  <section>
    <h4>Setup</h4>
    <dl>
      {#each roleLines(entry) as line (line.role)}
        <dt>{line.role}{#if kindOf(line.role)} <span class="pill kind">{kindOf(line.role)}</span>{/if}</dt><dd>{line.model}</dd>
      {/each}
      <dt>control</dt><dd>{setupPolicy(entry)}</dd>
      {#if params.length}<dt>parameters</dt><dd>{params.map(([k, v]) => `${k}=${String(v)}`).join(", ")}</dd>{/if}
    </dl>
    <p class="muted small">Fingerprint <code>{entry.fingerprint}</code>{#if entry.names.length > 1} · also ran as {entry.names.filter((n) => n !== entry.config).join(", ")}{/if}</p>
    <div class="actions">
      <button class="primary" onclick={onuse}>Use this setup →</button>
      {#if manifest}<a href={`#/scenarios/${manifest.id}/overview`}>About {manifest.title}</a>{/if}
    </div>
  </section>

  <section>
    {#if entry.criteria?.length}
      <h4>Pass criteria <span class="muted small">a trial passes when all hold · bar: share of checks met</span></h4>
      <ul class="criteria">
        {#each entry.criteria as c (c.name)}
          <li title={`${c.name}: passed in ${pct(c.pass_rate)} (per task), ${pct(c.credit)} of its checks met`}>
            <span class="name">{c.name}</span>
            <span class="bar" aria-hidden="true"><i style={`width:${c.credit * 100}%`}></i></span>
            <span class="n" class:fail={c.pass_rate < 1}>{pct(c.pass_rate)}</span>
          </li>
        {/each}
      </ul>
      {#if errors}<p class="muted small note">{errors} {errors === 1 ? "trial" : "trials"} ended in an error or timeout and
        {errors === 1 ? "counts" : "count"} as failing every criterion of {errors === 1 ? "its" : "their"} task.</p>{/if}
    {/if}
    <h4>Tasks <span class="muted small">{pct(entry.pass_rate)} over {entry.tasks} tasks · click a trial to walk through its steps</span></h4>
    <div class="grid" role="table" aria-label="Trials per task">
      {#each tasks as task (task)}
        <div class="task" role="row">
          <span class="name" role="rowheader" title={task}>{task}</span>
          <span class="cells" role="cell">
            {#each byTask[task] ?? [] as r (r.trial_id)}
              <a class="cell" class:ok={r.passed} class:bad={!r.passed && r.status === "ok"} class:err={r.status !== "ok"}
                href={inspect(r.run_id, r.trial_id)} style={partialFill(r)}
                title={`${r.passed ? "passed" : r.status === "ok" ? "failed" : r.status}${partialNote(r)} · run ${r.run_id}${r.repeat ? `, repeat ${r.repeat}` : ""} · open the step inspector`}
                aria-label={`${task}: ${r.passed ? "passed" : r.status === "ok" ? "failed" : r.status}${partialNote(r)}, run ${r.run_id}; open the step inspector`}>
                {r.passed ? "✓" : r.status === "ok" ? "✗" : "!"}</a>
            {/each}
          </span>
        </div>
      {/each}
    </div>
    <p class="muted small legend"><span class="cell ok">✓</span> passed <span class="cell bad">✗</span> failed
      (shaded by the share of checks met) <span class="cell err">!</span> error or timeout</p>
  </section>

  <section>
    <h4>Runs <span class="muted small">{entry.runs.length}</span></h4>
    <ul class="runs" bind:this={runList}>{#each entry.runs as run (run)}<li>
      <a href={`#/runs/${encodeURIComponent(run)}`}>{run}</a>
      <button class="link" data-run={run} onclick={() => startRename(run)} disabled={running.has(run) || renameRun === run}
        aria-label={`Rename run ${run}`} title={running.has(run) ? "A run can be renamed once it has finished" : undefined}>Rename</button>
    </li>{/each}</ul>
    <p class="muted small saved" role="status">{#if renamedRun}Saved the new names of run <code>{renamedRun}</code>.{/if}</p>
  </section>

  {#if renameRun}
    <section class="rename">
      {#if renameLoading}<p class="muted small" aria-busy="true">Loading run <code>{renameRun}</code>…</p>
      {:else if renameError}
        <p class="error" role="alert">Run <code>{renameRun}</code> could not be loaded: {renameError}
          <button class="link" onclick={() => closeRename(false)}>Close</button></p>
      {:else if renameBundle}
        <RenameForm runId={renameRun} bundle={renameBundle} onclose={closeRename} heading={`Rename run ${renameRun}`} />
      {/if}
    </section>
  {/if}
</div>

<style>
  .detail { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) minmax(0, 0.7fr); gap: 20px; padding: 14px 4px 6px; }
  @media (max-width: 1000px) { .detail { grid-template-columns: minmax(0, 1fr); } }
  h4 { margin: 0 0 8px; font-size: 13px; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  dl { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; font-size: 13px; }
  dt { color: var(--text-secondary); }
  dd { margin: 0; overflow-wrap: anywhere; }
  .kind { font-size: 10.5px; }
  .actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-top: 10px; }
  .actions button { white-space: nowrap; }
  .error { font-size: 13px; }
  .grid { display: grid; gap: 4px; max-height: 320px; overflow: auto; }
  .task { display: grid; grid-template-columns: minmax(90px, 180px) 1fr; gap: 8px; align-items: center; }
  .name { font-family: ui-monospace, monospace; font-size: 12px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cells { display: flex; gap: 4px; flex-wrap: wrap; }
  .cell { display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 5px; font-size: 13px; font-weight: 700;
    text-decoration: none; border: 1px solid var(--border); }
  .cell.ok { color: var(--good); background: color-mix(in srgb, var(--good) 14%, transparent); }
  .cell.bad { color: var(--critical); background: linear-gradient(to top, color-mix(in srgb, var(--good) 22%, transparent) var(--credit, 0%),
    color-mix(in srgb, var(--critical) 12%, transparent) var(--credit, 0%)); }
  .cell.err { color: var(--kind-decision); background: color-mix(in srgb, var(--kind-decision) 14%, transparent); }
  a.cell:hover, a.cell:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .legend { display: flex; align-items: center; gap: 6px; margin-top: 8px; }
  .legend .cell { width: 18px; height: 18px; font-size: 11px; }
  .note { margin: -8px 0 14px; }
  .criteria { list-style: none; margin: 0 0 14px; padding: 0; display: grid; gap: 6px; font-size: 12px; }
  .criteria li { display: grid; grid-template-columns: minmax(90px, 1fr) minmax(50px, 1fr) 40px; gap: 8px; align-items: center; }
  .criteria .name { font-family: ui-monospace, monospace; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .criteria .bar { position: relative; height: 6px; background: var(--surface-3); border-radius: 3px; overflow: hidden; }
  .criteria .bar i { position: absolute; inset: 0 auto 0 0; background: var(--accent); opacity: 0.6; }
  .criteria .n { text-align: right; font-variant-numeric: tabular-nums; }
  .criteria .fail { color: var(--critical); }
  .runs { margin: 0; padding-left: 16px; font-size: 13px; display: grid; gap: 6px; }
  .runs li { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .saved { margin: 6px 0 0; }
  .saved:empty { margin: 0; }
  .rename { grid-column: 1 / -1; }
  .link { font-size: 13px; }
</style>
