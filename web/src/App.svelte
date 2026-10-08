<script lang="ts">
  import { app, refresh } from "./lib/app.svelte";
  import { detectLocalBackend, exchangeSession } from "./lib/backend";
  import { enforceCredentialStorage } from "./lib/credential-storage";
  import { WorkerBackend } from "./lib/worker-backend";
  import SelftestView from "./views/SelftestView.svelte";
  import { router } from "./lib/router.svelte";
  import { activeRuns, watchRuns } from "./lib/runs.svelte";
  import { serverIsOlder, update, watchUpdates } from "./lib/update.svelte";
  import { WIKI_HOME } from "./lib/wiki";
  import ExperimentsView from "./views/ExperimentsView.svelte";
  import HomeView from "./views/HomeView.svelte";
  import LeaderboardView from "./views/LeaderboardView.svelte";
  import ScenarioView from "./views/ScenarioView.svelte";
  import PresetsView from "./views/PresetsView.svelte";
  import ModelsView from "./views/ModelsView.svelte";
  import RunsView from "./views/RunsView.svelte";
  import RunView from "./views/RunView.svelte";

  let unlockValue = $state("");
  let unlockError = $state("");

  function tokenFrom(value: string): string {
    const marker = "#token=";
    return value.includes(marker) ? decodeURIComponent(value.slice(value.indexOf(marker) + marker.length)) : value.trim();
  }

  async function connectLocal(token = "") {
    unlockError = "";
    try {
      if (token) await exchangeSession(token);
      const backend = await detectLocalBackend();
      if (backend) {
        if (backend.locked) {
          app.backend = null;
          app.mode = "locked";
          return;
        }
        app.backend = backend;
        app.mode = "local";
        await refresh();
        return;
      }
      app.mode = "browser";
      const wheel = new URL("py/llm_arena-0.1.0-py3-none-any.whl", document.baseURI).href;
      const worker = new WorkerBackend(wheel, (message) => (app.status = message));
      await worker.ready;
      app.backend = worker;
      app.status = "";
      await refresh();
    } catch (error) {
      unlockError = error instanceof Error ? error.message : String(error);
      if (app.mode === "browser") app.error = unlockError;
      else app.mode = "locked";
    }
  }

  async function unlock() {
    await connectLocal(tokenFrom(unlockValue));
    unlockValue = "";
  }

  $effect(() => {
    const credentialPolicy = enforceCredentialStorage();
    app.canRememberKeys = credentialPolicy.canRemember;
    if (credentialPolicy.removedLegacyKeys) {
      app.credentialNotice = "Previously remembered API keys were removed because this site is not an approved credential origin.";
    }
    const fragment = location.hash.startsWith("#token=") ? tokenFrom(location.hash) : "";
    if (fragment) history.replaceState(null, "", `${location.pathname}${location.search}#/`);
    void connectLocal(fragment);
    const lock = () => { app.backend = null; app.mode = "locked"; };
    window.addEventListener("arena-auth-required", lock);
    return () => window.removeEventListener("arena-auth-required", lock);
  });

  const providers = $derived(Object.entries(app.runtime?.providers ?? {}));
  $effect(() => (app.backend ? watchRuns() : undefined));
  $effect(() => watchUpdates());
  const live = $derived(activeRuns());
  const liveTitle = $derived(live.length ? `${live.length} run${live.length > 1 ? "s" : ""} in progress: `
    + `${live.reduce((n, r) => n + (r.progress?.running ?? 0), 0)} trials running, `
    + `${live.reduce((n, r) => n + (r.progress?.queued ?? 0), 0)} queued` : "");
  // Where model-written code runs (chart, CodeAct and coding-benchmark scenarios).
  const SANDBOX: Record<string, { label: string; title: string; warn: boolean }> = {
    container: { label: "sandbox: Docker", title: "Model-written code runs in Docker: no network, no host files, resource limits.", warn: false },
    process: { label: "sandbox: local process", title: "Model-written code runs as a local process with your user's permissions and network access, not isolated. Start Docker and run make sandbox-image, then restart the app (or use --sandbox docker).", warn: true },
    "browser worker": { label: "browser sandbox", title: "Model-written code runs in a fresh, disposable Pyodide worker in this tab.", warn: false },
  };
  // Containers always run as the user; the daemon that starts them may run as root (standard Linux install).
  const DAEMON: Record<string, { label: string; title: string }> = {
    rootless: { label: ", rootless", title: " The Docker daemon runs rootless: no part of the sandbox runs as root." },
    root: { label: ", root daemon", title: " The Docker daemon runs as root (standard Linux install); the containers run as your user. Rootless Docker avoids root entirely." },
    vm: { label: "", title: " Docker runs inside a virtual machine (e.g. Docker Desktop), not directly on this system." },
  };
  const sandbox = $derived.by(() => {
    const base = SANDBOX[app.runtime?.sandbox_isolation ?? ""];
    if (base && app.runtime?.sandbox_isolation === "browser worker") {
      const isolated = app.runtime.sandbox_network_isolation === "isolated";
      return { ...base, label: `browser sandbox: ${isolated ? "isolated" : "not network-isolated"}`,
        title: `${base.title} ${isolated ? "The runtime canary confirmed network denial in an opaque origin." : "The runtime could not prove a browser-enforced network boundary."}`,
        warn: !isolated };
    }
    const daemon = base && app.runtime?.sandbox_isolation === "container" ? DAEMON[app.runtime?.sandbox_daemon ?? ""] : undefined;
    return base ? { ...base, label: base.label + (daemon?.label ?? ""), title: base.title + (daemon?.title ?? "") } : null;
  });
  const nav = [
    { href: "#/", label: "Scenarios", match: "home" },
    { href: "#/experiments", label: "Experiments", match: "experiments" },
    { href: "#/models", label: "Models", match: "models" },
    { href: "#/runs", label: "Runs", match: "runs" },
    { href: "#/leaderboard", label: "Leaderboard", match: "leaderboard" },
    { href: "#/presets", label: "Presets", match: "presets" },
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
  {#if app.credentialNotice}
    <p class="note credential-notice" role="status"><span>{app.credentialNotice}</span>
      <button onclick={() => (app.credentialNotice = "")}>Dismiss</button></p>
  {/if}
  {#if update.available}
    <p class="note update" role="status"><span>A newer version of the arena is available; this tab still runs the old one.
      {#if app.mode === "browser" && live.length}Runs in this tab stop when you reload.{/if}</span>
      <button class="primary" onclick={() => location.reload()}>Reload</button></p>
  {:else if app.mode === "local" && serverIsOlder(app.runtime?.ui_build)}
    <p class="note update" role="status"><span>The arena server was started before this version of the app, so newer features may
      fail. Restart it: stop <code>make ui</code> (Ctrl+C) and start it again.</span></p>
  {/if}
  {#if app.mode === "detecting"}
    <p class="muted">Connecting…</p>
  {:else if app.mode === "locked"}
    <section class="locked" aria-labelledby="locked-title">
      <h1 id="locked-title">Local arena locked</h1>
      <p class="lead">Open the link printed by <code>arena ui</code>, or run <code>arena ui --link</code>.</p>
      <form onsubmit={(event) => { event.preventDefault(); void unlock(); }}>
        <label for="unlock-token">Authenticated link or token</label>
        <div class="unlock"><input id="unlock-token" type="password" autocomplete="off" bind:value={unlockValue} />
          <button class="primary" type="submit" disabled={!unlockValue.trim()}>Unlock</button></div>
      </form>
      {#if unlockError}<p class="note" role="alert">{unlockError}</p>{/if}
    </section>
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
    {:else if router.route.name === "experiments"}<ExperimentsView template={router.route.template} />
    {:else if router.route.name === "models"}<ModelsView />
    {:else if router.route.name === "runs"}<RunsView />
    {:else if router.route.name === "leaderboard"}<LeaderboardView scenario={router.route.scenario} entry={router.route.entry} />
    {:else if router.route.name === "presets"}<PresetsView />
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
  .update { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; justify-content: space-between; margin: 0 0 16px; }
  .credential-notice { display: flex; gap: 12px; align-items: center; justify-content: space-between; margin: 0 0 16px; }
  main { max-width: 1180px; margin: 0 auto; padding: 24px 16px 80px; }
  .locked { max-width: 620px; margin: 64px auto; }
  .locked form { margin-top: 24px; }
  .locked label { display: block; font-weight: 600; margin-bottom: 6px; }
  .unlock { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
</style>
