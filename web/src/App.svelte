<script lang="ts">
  import { app, refresh } from "./lib/app.svelte";
  import { detectLocalBackend } from "./lib/backend";
  import { WorkerBackend } from "./lib/worker-backend";
  import SelftestView from "./views/SelftestView.svelte";
  import { router } from "./lib/router.svelte";
  import { activeRuns, watchRuns } from "./lib/runs.svelte";
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
  $effect(() => (app.backend ? watchRuns() : undefined));
  const live = $derived(activeRuns());
  const liveTitle = $derived(live.length ? `${live.length} run${live.length > 1 ? "s" : ""} in progress: `
    + `${live.reduce((n, r) => n + (r.progress?.running ?? 0), 0)} trials running, `
    + `${live.reduce((n, r) => n + (r.progress?.queued ?? 0), 0)} queued` : "");
  // Where model-written code runs (chart, CodeAct and coding-benchmark scenarios).
  const SANDBOX: Record<string, { label: string; title: string; warn: boolean }> = {
    container: { label: "sandbox: Docker", title: "Model-written code runs in Docker: no network, no host files, resource limits.", warn: false },
    process: { label: "sandbox: local process", title: "Model-written code runs as a local process with your user's permissions and network access, not isolated. Start Docker and run make sandbox-image, then restart the app (or use --sandbox docker).", warn: true },
    "browser worker": { label: "sandbox: browser worker", title: "Model-written code runs in a separate Pyodide worker in this tab.", warn: false },
  };
  const sandbox = $derived(SANDBOX[app.runtime?.sandbox_isolation ?? ""] ?? null);
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
      <a href={item.href} class:active={router.route.name === item.match || (item.match === "runs" && router.route.name === "run")}>{item.label}{#if item.match === "runs" && live.length}
        <span class="live-badge" title={liveTitle} aria-label={liveTitle}><span class="dot" aria-hidden="true"></span>{live.length}</span>{/if}</a>
    {/each}
    <a href={WIKI_HOME} target="_blank" rel="noopener">Wiki ↗</a>
  </nav>
  <span class="status">
    {#if app.mode === "local"}
      <span class="pill on" title="Connected to the arena server on this machine (arena ui): local models and keys from .env">local app</span>
      {#if sandbox}<span class="pill" class:warn={sandbox.warn} title={sandbox.title}>{sandbox.warn ? "⚠ " : ""}{sandbox.label}</span>{/if}
      {#each providers as [name, state] (name)}<span class="pill" title={state}>{state === "available" ? "●" : "○"} {name}</span>{/each}
    {:else if app.mode === "browser"}
      <span class="pill on" title="The arena engine runs in this browser tab: remote models only">browser mode</span>
      {#if sandbox}<span class="pill" title={sandbox.title}>{sandbox.label}</span>{/if}
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
    {:else if router.route.name === "leaderboard"}<LeaderboardView scenario={router.route.scenario} entry={router.route.entry} />
    {:else if router.route.name === "settings"}<SettingsView />
    {:else if router.route.name === "scenario"}{#key router.route.id}<ScenarioView id={router.route.id} tab={router.route.tab} />{/key}
    {:else if router.route.name === "run"}<RunView id={router.route.id} trial={router.route.trial} step={router.route.step} />
    {:else if router.route.name === "selftest"}<SelftestView />
    {/if}
  {/if}
</main>

<style>
  .live-badge { display: inline-flex; align-items: center; gap: 4px; margin-left: 6px; padding: 0 7px; height: 18px; border-radius: 999px;
    background: var(--accent); color: var(--accent-ink); font-size: 11px; font-weight: 600; vertical-align: 1px; font-variant-numeric: tabular-nums; }
  .live-badge .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; animation: blink 1.4s ease-in-out infinite; }
  @keyframes blink { 50% { opacity: 0.3; } }
  @media (prefers-reduced-motion: reduce) { .live-badge .dot { animation: none; } }
  .pill.warn { color: var(--critical); border-color: var(--critical); }
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
