<script lang="ts">
  import type { LeaderboardEntry, ScenarioManifest } from "../lib/contracts";
  import { pct } from "../lib/format";
  import { roleLines, setupPolicy } from "../lib/leaderboard";

  // One leaderboard entry opened up: what it ran, how each task went (every cell opens that trial's step
  // inspector), and the runs it comes from.
  let { entry, manifest, onuse }: { entry: LeaderboardEntry; manifest?: ScenarioManifest; onuse: () => void } = $props();

  const tasks = $derived([...new Set((entry.results ?? []).map((r) => r.task_id))]);
  const byTask = $derived(Object.fromEntries(tasks.map((t) => [t, (entry.results ?? []).filter((r) => r.task_id === t)])));
  const params = $derived(Object.entries((entry.setup.params ?? {}) as Record<string, unknown>));
  const inspect = (runId: string, trialId: string) => `#/runs/${encodeURIComponent(runId)}/trial/${encodeURIComponent(trialId)}`;
  const kindOf = (role: string) => manifest?.roles.find((r) => r.name === role)?.kind ?? "";
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
    <h4>Tasks <span class="muted small">{pct(entry.pass_rate)} over {entry.tasks} tasks · click a trial to walk through its steps</span></h4>
    <div class="grid" role="table" aria-label="Trials per task">
      {#each tasks as task (task)}
        <div class="task" role="row">
          <span class="name" role="rowheader" title={task}>{task}</span>
          <span class="cells" role="cell">
            {#each byTask[task] ?? [] as r (r.trial_id)}
              <a class="cell" class:ok={r.passed} class:bad={!r.passed && r.status === "ok"} class:err={r.status !== "ok"}
                href={inspect(r.run_id, r.trial_id)}
                title={`${r.passed ? "passed" : r.status === "ok" ? "failed" : r.status} · run ${r.run_id}${r.repeat ? `, repeat ${r.repeat}` : ""} · open the step inspector`}
                aria-label={`${task}: ${r.passed ? "passed" : r.status === "ok" ? "failed" : r.status}, run ${r.run_id}; open the step inspector`}>
                {r.passed ? "✓" : r.status === "ok" ? "✗" : "!"}</a>
            {/each}
          </span>
        </div>
      {/each}
    </div>
    <p class="muted small legend"><span class="cell ok">✓</span> passed <span class="cell bad">✗</span> failed
      <span class="cell err">!</span> error or timeout</p>
  </section>

  <section>
    <h4>Runs <span class="muted small">{entry.runs.length}</span></h4>
    <ul class="runs">{#each entry.runs as run (run)}<li><a href={`#/runs/${encodeURIComponent(run)}`}>{run}</a></li>{/each}</ul>
  </section>
</div>

<style>
  .detail { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) minmax(0, 0.7fr); gap: 20px; padding: 14px 4px 6px; }
  @media (max-width: 1000px) { .detail { grid-template-columns: minmax(0, 1fr); } }
  h4 { margin: 0 0 8px; font-size: 13px; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  dl { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; font-size: 13px; }
  dt { color: var(--text-secondary); }
  dd { margin: 0; overflow-wrap: anywhere; }
  .kind { font-size: 10.5px; }
  .small { font-size: 12px; }
  .actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-top: 10px; }
  .actions button { white-space: nowrap; }
  .grid { display: grid; gap: 4px; max-height: 320px; overflow: auto; }
  .task { display: grid; grid-template-columns: minmax(90px, 180px) 1fr; gap: 8px; align-items: center; }
  .name { font-family: ui-monospace, monospace; font-size: 12px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cells { display: flex; gap: 4px; flex-wrap: wrap; }
  .cell { display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 5px; font-size: 13px; font-weight: 700;
    text-decoration: none; border: 1px solid var(--border); }
  .cell.ok { color: var(--good); background: color-mix(in srgb, var(--good) 14%, transparent); }
  .cell.bad { color: var(--critical); background: color-mix(in srgb, var(--critical) 12%, transparent); }
  .cell.err { color: var(--kind-decision); background: color-mix(in srgb, var(--kind-decision) 14%, transparent); }
  a.cell:hover, a.cell:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .legend { display: flex; align-items: center; gap: 6px; margin-top: 8px; }
  .legend .cell { width: 18px; height: 18px; font-size: 11px; }
  .runs { margin: 0; padding-left: 16px; font-size: 13px; display: grid; gap: 2px; }
</style>
