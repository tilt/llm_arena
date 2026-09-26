<script lang="ts">
  import { app, refresh } from "./lib/app.svelte";
  import { detectLocalBackend } from "./lib/backend";
  import { router } from "./lib/router.svelte";
  import { WIKI_HOME } from "./lib/wiki";
  import BuildView from "./views/BuildView.svelte";
  import HomeView from "./views/HomeView.svelte";
  import ModelsView from "./views/ModelsView.svelte";
  import RunsView from "./views/RunsView.svelte";
  import RunView from "./views/RunView.svelte";

  $effect(() => {
    detectLocalBackend().then(async (backend) => {
      if (backend) {
        app.backend = backend;
        app.mode = "local";
        await refresh();
      } else {
        app.mode = "browser";
      }
    });
  });

  const providers = $derived(Object.entries(app.runtime?.providers ?? {}));
  const nav = [
    { href: "#/", label: "Overview", match: "home" },
    { href: "#/build", label: "Build", match: "build" },
    { href: "#/models", label: "Models", match: "models" },
    { href: "#/runs", label: "Runs", match: "runs" },
  ];
</script>

<header>
  <a class="brand" href="#/">LLM Arena</a>
  <nav>
    {#each nav as item (item.href)}
      <a href={item.href} class:active={router.route.name === item.match || (item.match === "runs" && router.route.name === "run")}>{item.label}</a>
    {/each}
    <a href={WIKI_HOME} target="_blank" rel="noopener">Wiki ↗</a>
  </nav>
  <span class="status">
    {#if app.mode === "local"}
      <span class="pill on">local app</span>
      {#each providers as [name, state] (name)}<span class="pill" title={state}>{state === "available" ? "●" : "○"} {name}</span>{/each}
    {:else if app.mode === "browser"}
      <span class="pill">browser mode</span>
    {/if}
  </span>
</header>

<main>
  {#if app.mode === "detecting"}
    <p class="muted">Connecting…</p>
  {:else if app.mode === "browser" && !app.backend}
    <h1>LLM Arena</h1>
    <p class="lead">
      This page is not served by the local app. Browser-only mode (running the arena in this tab with your own API key)
      comes next. For now, install and run it locally:
    </p>
    <pre>git clone https://github.com/tilt/llm_arena && cd llm_arena
make install && make web && uv run arena ui</pre>
  {:else}
    {#if app.error}<p class="note">{app.error}</p>{/if}
    {#if router.route.name === "home"}<HomeView />
    {:else if router.route.name === "build"}<BuildView />
    {:else if router.route.name === "models"}<ModelsView />
    {:else if router.route.name === "runs"}<RunsView />
    {:else if router.route.name === "run"}<RunView id={router.route.id} />
    {/if}
  {/if}
</main>

<style>
  header { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; padding: 12px 16px; border-bottom: 1px solid var(--border);
    background: var(--surface-1); position: sticky; top: 0; z-index: 10; }
  .brand { font-weight: 700; color: var(--text-primary); text-decoration: none; font-size: 16px; }
  nav { display: flex; gap: 4px; flex-wrap: wrap; }
  nav a { color: var(--text-secondary); text-decoration: none; padding: 4px 10px; border-radius: 6px; font-size: 14px; }
  nav a:hover { background: var(--surface-2); }
  nav a.active { background: var(--surface-2); color: var(--text-primary); font-weight: 600; }
  .status { margin-left: auto; }
  main { max-width: 1180px; margin: 0 auto; padding: 24px 16px 80px; }
</style>
