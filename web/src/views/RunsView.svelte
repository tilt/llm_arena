<script lang="ts">
  import { app } from "../lib/app.svelte";
  import type { RunListing } from "../lib/contracts";
  import { pct } from "../lib/format";

  let runs = $state<RunListing[] | null>(null);
  let error = $state("");

  $effect(() => {
    app.backend?.runs().then((r) => (runs = r)).catch((e: unknown) => (error = String(e)));
  });
</script>

<h1>Runs</h1>
<p class="lead">Past and active runs. Open one to follow its progress or read its report.</p>
{#if error}<p class="note">{error}</p>{/if}
<div class="card table-wrap">
  <table>
    <thead><tr><th>Run</th><th>Experiment</th><th>Started</th><th class="n">Trials</th><th class="n">Pass rate</th><th class="n">Errors</th><th>Status</th></tr></thead>
    <tbody>
      {#each runs ?? [] as run (run.run_id)}
        <tr>
          <td><a href={`#/runs/${encodeURIComponent(run.run_id)}`}>{run.run_id}</a></td>
          <td>{run.name}</td><td class="muted">{run.created_at}</td>
          <td class="n">{run.trials}</td><td class="n">{pct(run.trials ? run.passed / run.trials : null)}</td>
          <td class="n">{#if run.errors}<span class="fail">{run.errors}</span>{:else}0{/if}</td>
          <td>{#if run.active}<span class="pill on">running</span>{:else}<span class="pill">done</span>{/if}</td>
        </tr>
      {:else}
        <tr><td colspan="7" class="muted">{runs === null ? "Loading…" : "No runs yet."} <a href="#/build">Build an experiment</a>.</td></tr>
      {/each}
    </tbody>
  </table>
</div>
