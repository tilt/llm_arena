<script lang="ts">
  import { app } from "../lib/app.svelte";
  import type { TaskView } from "../lib/contracts";
  import ExpectationView from "./ExpectationView.svelte";

  // A scenario's tasks: searchable and filterable, each opening to its prompt and expected outcome.
  let { scenario, onrun }: { scenario: string; onrun?: (taskId: string) => void } = $props();

  let tasks = $state<TaskView[]>([]);
  let loading = $state(true);
  let error = $state("");
  let query = $state("");
  let tag = $state("");
  let split = $state("");

  $effect(() => {
    loading = true; error = ""; tasks = [];
    app.backend?.tasks(scenario).then(
      (found) => { tasks = found; loading = false; },
      (e) => { error = e instanceof Error ? e.message : String(e); loading = false; },
    );
  });

  const tags = $derived([...new Set(tasks.flatMap((t) => t.tags ?? []))].sort());
  const splits = $derived([...new Set(tasks.map((t) => t.split).filter(Boolean))] as string[]);
  const needle = $derived(query.trim().toLowerCase());
  const visible = $derived(tasks.filter((t) =>
    (!tag || (t.tags ?? []).includes(tag)) && (!split || t.split === split)
    && (!needle || `${t.id} ${t.prompt}`.toLowerCase().includes(needle))));
  const firstLine = (text: string) => (text.length > 140 ? `${text.slice(0, 139)}…` : text).split("\n")[0];
</script>

{#if loading}
  <div class="skeletons" aria-busy="true" aria-label="Loading tasks">{#each [1, 2, 3, 4] as i (i)}<div class="skeleton"></div>{/each}</div>
{:else if error}
  <p class="note" role="alert">The tasks could not be loaded: {error}</p>
{:else}
  <div class="filters">
    <label class="search"><span class="sr-only">Search tasks</span>
      <input type="search" placeholder="Search id or prompt…" bind:value={query} /></label>
    {#if tags.length}
      <select bind:value={tag} aria-label="Filter by tag"><option value="">All tags</option>{#each tags as t (t)}<option value={t}>{t}</option>{/each}</select>
    {/if}
    {#if splits.length}
      <select bind:value={split} aria-label="Filter by split"><option value="">All splits</option>{#each splits as s (s)}<option value={s}>{s}</option>{/each}</select>
    {/if}
    <span class="muted" aria-live="polite">{visible.length} of {tasks.length} tasks</span>
  </div>
  {#if !visible.length}
    <p class="muted">No task matches. <button class="link" onclick={() => { query = ""; tag = ""; split = ""; }}>Clear the filters</button></p>
  {/if}
  <div class="list">
    {#each visible as task (task.id)}
      <details class="task card">
        <summary>
          <span class="id">{task.id}</span>
          <span class="prompt">{firstLine(task.prompt)}</span>
          <span class="pills">{#if task.split}<span class="pill">{task.split}</span>{/if}{#each (task.tags ?? []).slice(0, 3) as t (t)}<span class="pill">{t}</span>{/each}</span>
        </summary>
        <div class="body">
          <div>
            <h4>Prompt</h4>
            <p class="full">{task.prompt}</p>
            {#if task.note}<p class="note">{task.note}</p>{/if}
          </div>
          <div class="expected">
            <h4>Counts as correct</h4>
            {#each task.expected as expectation, i (i)}<ExpectationView {expectation} />{/each}
          </div>
          {#if onrun}<div class="actions"><button onclick={() => onrun(task.id)}>Run only this task →</button></div>{/if}
        </div>
      </details>
    {/each}
  </div>
{/if}

<style>
  .filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }
  .search input { min-width: 240px; }
  .list { display: grid; gap: 8px; }
  .task { padding: 0; }
  .task summary { display: grid; grid-template-columns: minmax(120px, 200px) 1fr auto; gap: 12px; align-items: center; padding: 12px 14px;
    cursor: pointer; list-style: none; }
  .task summary::-webkit-details-marker { display: none; }
  .task summary::before { content: "▸"; color: var(--text-muted); position: absolute; margin-left: -10px; transition: transform 0.15s; }
  .task[open] summary::before { transform: rotate(90deg); }
  @media (prefers-reduced-motion: reduce) { .task summary::before { transition: none; } }
  .task[open] summary { border-bottom: 1px solid var(--border); }
  .task summary:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; border-radius: var(--radius); }
  .id { font-family: ui-monospace, monospace; font-size: 12.5px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; }
  .prompt { color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pills { display: flex; gap: 4px; }
  .body { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 14px; }
  .body .actions { grid-column: 1 / -1; }
  .full { white-space: pre-wrap; margin: 0; }
  .expected { display: grid; gap: 10px; align-content: start; }
  h4 { margin: 0 0 6px; font-size: 13px; }
  .skeletons { display: grid; gap: 8px; }
  .skeleton { height: 46px; border-radius: var(--radius); background: var(--surface-2); }
  .link { background: none; border: none; color: var(--accent); padding: 0; text-decoration: underline; cursor: pointer; }
  @media (max-width: 760px) {
    .task summary { grid-template-columns: 1fr; gap: 4px; }
    .prompt { white-space: normal; }
    .body { grid-template-columns: 1fr; }
  }
</style>
