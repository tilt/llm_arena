<script lang="ts">
  import { app, refresh } from "./lib/app.svelte";
  import { detectLocalBackend } from "./lib/backend";
  import { WorkerBackend } from "./lib/worker-backend";
  import SelftestView from "./views/SelftestView.svelte";
  import { router } from "./lib/router.svelte";
  import { WIKI_HOME } from "./lib/wiki";
  import BuildView from "./views/BuildView.svelte";
  import HomeView from "./views/HomeView.svelte";
  import LeaderboardView from "./views/LeaderboardView.svelte";
  import ScenarioView from "./views/ScenarioView.svelte";
  import SettingsView from "./views/SettingsView.svelte";
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
        const wheel = new URL("py/llm_arena-0.1.0-py3-none-any.whl", document.baseURI).href;
        const worker = new WorkerBackend(wheel, (message) => (app.status = message));
        try {
          await worker.ready;
          app.backend = worker;
          app.status = "";
          await refresh();
        } catch (error) {
          app.error = `The in-browser engine could not start: ${error instanceof Error ? error.message : String(error)}`;
        }
      }
    });
  });

  const providers = $derived(Object.entries(app.runtime?.providers ?? {}));
  const nav = [
    { href: "#/", label: "Scenarios", match: "home" },
    { href: "#/build", label: "Build", match: "build" },
    { href: "#/models", label: "Models", match: "models" },
    { href: "#/runs", label: "Runs", match: "runs" },
    { href: "#/leaderboard", label: "Leaderboard", match: "leaderboard" },
    { href: "#/settings", label: "Baselines", match: "settings" },
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
      <span class="pill on">browser mode</span>
      {#each providers as [name, state] (name)}<span class="pill" title={state}>{state === "available" ? "●" : "○"} {name}</span>{/each}
    {/if}
  </span>
</header>

<main>
  {#if app.mode === "detecting"}
    <p class="muted">Connecting…</p>
  {:else if app.mode === "browser" && !app.backend}
    <h1>LLM Arena</h1>
    {#if app.error}
      <p class="note">{app.error}</p>
    {:else}
      <p class="lead">{app.status || "Starting the in-browser engine…"}</p>
      <p class="muted">The arena's Python engine runs in this tab (Pyodide). It is cached after the first visit.</p>
    {/if}
  {:else}
    {#if app.error}<p class="note">{app.error}</p>{/if}
    {#if router.route.name === "home"}<HomeView />
    {:else if router.route.name === "build"}<BuildView />
    {:else if router.route.name === "models"}<ModelsView />
    {:else if router.route.name === "runs"}<RunsView />
    {:else if router.route.name === "leaderboard"}<LeaderboardView />
    {:else if router.route.name === "settings"}<SettingsView />
    {:else if router.route.name === "scenario"}{#key router.route.id}<ScenarioView id={router.route.id} tab={router.route.tab} />{/key}
    {:else if router.route.name === "run"}<RunView id={router.route.id} trial={router.route.trial} step={router.route.step} />
    {:else if router.route.name === "selftest"}<SelftestView />
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
