<script lang="ts">
  import { app } from "../lib/app.svelte";
  import { EVALUATION_PAGES } from "../lib/builder";
  import { REPO_URL, WIKI_HOME } from "../lib/wiki";

  const patterns = $derived(app.scenarios.filter((s) => s.kind === "pattern"));
  const evaluationLinks = $derived((app.scenarios[0]?.wiki ?? []).filter((link) => EVALUATION_PAGES.has(link.title)));
  const benchmarks = $derived(app.scenarios.filter((s) => s.kind === "benchmark"));
</script>

<h1>LLM Arena</h1>
<p class="lead">
  Compare local and remote language models on agentic AI patterns (reflection, tool use, code execution, ReAct,
  planning, multi-agent) and classic benchmarks. Every pipeline step is bound to a model you choose and scored on its
  own and end to end. Background reading on each pattern is in the
  <a href={WIKI_HOME} target="_blank" rel="noopener">data-science wiki</a>.
</p>

{#if app.mode === "browser"}
  <section class="card intro">
    <h2>Running in your browser</h2>
    <p>
      The arena engine runs in this tab. To compare remote models, add an <a href="#/models">OpenAI or Anthropic key</a>.
      It stays in this tab and goes only to the provider. Then <a href="#/build">build an experiment</a> with a small
      spend limit.
    </p>
    <p>
      <strong>Local models (Ollama, LM Studio)?</strong> A web page cannot reach them, so run the app on your machine.
      It discovers your installed models and reads keys from <code>.env</code>:
    </p>
    <pre>git clone {REPO_URL}.git && cd llm_arena
make install && make web && uv run arena ui</pre>
  </section>
{/if}

<div class="actions">
  <a class="cta" href="#/build">Build an experiment →</a>
  <a class="cta secondary" href="#/models">See available models</a>
  <a class="cta secondary" href="#/runs">Past runs</a>
</div>

<h2>Agentic patterns</h2>
<div class="cards">
  {#each patterns as s (s.id)}
    <article class="card">
      <div class="top"><strong>{s.title}</strong><span class="pill">{s.pattern}</span></div>
      <p>{s.description}</p>
      <p class="muted small">{s.tasks} tasks · roles: {s.roles.map((r) => r.name).join(", ")}{(s.requires ?? []).length ? ` · needs ${s.requires?.join(", ")}` : ""}</p>
      <p class="small">{#each (s.wiki ?? []).filter((link) => !EVALUATION_PAGES.has(link.title)) as link (link.url)}<a href={link.url} target="_blank" rel="noopener">{link.title}</a>{/each}</p>
    </article>
  {/each}
</div>

<p class="muted small">How the arena evaluates:
  {#each evaluationLinks as link (link.url)}<a href={link.url} target="_blank" rel="noopener">{link.title}</a>{/each}</p>

<h2>Benchmarks</h2>
<div class="cards">
  {#each benchmarks as s (s.id)}
    <article class="card"><div class="top"><strong>{s.title}</strong></div><p>{s.description}</p></article>
  {/each}
</div>

<p class="muted small footer">Source, CLI and local app: <a href={REPO_URL} target="_blank" rel="noopener">{REPO_URL}</a></p>

<style>
  .actions { display: flex; gap: 12px; flex-wrap: wrap; margin: 20px 0 8px; }
  .cta { background: var(--accent); color: var(--accent-ink); padding: 8px 16px; border-radius: 8px; text-decoration: none; font-weight: 600; }
  .cta.secondary { background: var(--surface-2); color: var(--text-primary); border: 1px solid var(--border); font-weight: 500; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
  .top { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
  .card p { margin: 6px 0; font-size: 14px; color: var(--text-secondary); }
  .small { font-size: 12px !important; }
  .small a { margin-right: 10px; }
  .footer { margin-top: 32px; }
  .intro { margin: 16px 0; }
  .intro h2 { margin-top: 0; }
  .intro code { background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
</style>
