<script lang="ts">
  import { app } from "../lib/app.svelte";
  import { WorkerBackend, type SelftestResult } from "../lib/worker-backend";

  let results = $state<SelftestResult[] | null>(null);
  let error = $state("");
  let running = $state(false);

  async function run() {
    if (!(app.backend instanceof WorkerBackend)) return;
    running = true;
    error = "";
    try {
      const vectors = (await (await fetch(new URL("py/conformance.json", document.baseURI))).json()) as Record<string, unknown>;
      results = await app.backend.selftest(vectors);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      running = false;
    }
  }
</script>

<h1>Engine self-test</h1>
<p class="lead">
  Replays the conformance vectors (scripted model replies with known requests and scores) in this browser's engine
  and compares them with the Python engine's results. No API calls are made.
</p>
{#if app.backend instanceof WorkerBackend}
  <button class="primary" onclick={run} disabled={running}>{running ? "Running…" : "Run self-test"}</button>
{:else}
  <p class="muted">The self-test checks the in-browser engine; this page is served by the local app.</p>
{/if}
{#if error}<p class="note">{error}</p>{/if}
{#if results}
  <p id="selftest-summary"><strong>{results.filter((r) => r.status === "pass").length} passed</strong>,
    {results.filter((r) => r.status === "fail").length} failed, {results.filter((r) => r.status === "skipped").length} skipped</p>
  <div class="card table-wrap">
    <table>
      <thead><tr><th>Case</th><th>Result</th><th>Details</th></tr></thead>
      <tbody>
        {#each results as r (r.case)}
          <tr><td>{r.case}</td><td class={r.status === "pass" ? "pass" : r.status === "fail" ? "fail" : "muted"}>{r.status}</td>
            <td class="muted">{r.mismatches?.join(", ") ?? r.reason ?? ""}</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}
