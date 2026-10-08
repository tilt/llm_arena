<script lang="ts">
  import { app, refresh } from "../lib/app.svelte";
  import type { EndpointView } from "../lib/contracts";
  import { endpointHint, endpointIdProblem, endpointUrlProblem } from "../lib/endpoints";

  // Named OpenAI-compatible endpoints: a self-hosted or third-party server's models appear as "<name>:<model>".
  const CAPS = [
    { key: "tools", label: "tool calling" },
    { key: "json_schema", label: "JSON schema output" },
    { key: "vision", label: "vision" },
    { key: "reasoning", label: "thinking" },
  ] as const;
  type Caps = Record<(typeof CAPS)[number]["key"], boolean>;
  const blank = () => ({ id: "", base_url: "", key: "", caps: { tools: true, json_schema: true, vision: false, reasoning: false } as Caps,
    input: "", output: "" });

  let endpoints = $state<EndpointView[]>([]);
  let form = $state(blank());
  let editing = $state("");
  let remember = $state(false);
  let busy = $state(false);
  let message = $state("");

  const idProblem = $derived(editing || !form.id ? "" : endpointIdProblem(form.id));
  const urlProblem = $derived(form.base_url ? endpointUrlProblem(form.base_url, !!form.key) : "");
  const taken = $derived(!editing && endpoints.some((e) => e.id === form.id));
  const ready = $derived(!!form.id && !!form.base_url && !idProblem && !urlProblem && !taken);
  const models = (id: string) => (app.models?.models ?? []).filter((m) => m.endpoint === id).length;

  async function load() {
    if (!app.backend) return;
    try { endpoints = await app.backend.endpoints(); } catch (error) { message = error instanceof Error ? error.message : String(error); }
  }
  $effect(() => { if (app.backend) void load(); });

  function edit(endpoint: EndpointView) {
    editing = endpoint.id;
    const caps = endpoint.capabilities ?? {};
    form = { id: endpoint.id, base_url: endpoint.base_url, key: "",
      caps: { tools: caps.tools ?? true, json_schema: caps.json_schema ?? true, vision: !!caps.vision, reasoning: !!caps.reasoning },
      input: endpoint.input_cost_per_mtok ? String(endpoint.input_cost_per_mtok) : "",
      output: endpoint.output_cost_per_mtok ? String(endpoint.output_cost_per_mtok) : "" };
  }

  function reset() {
    editing = "";
    form = blank();
  }

  async function save() {
    if (!app.backend || !ready) return;
    busy = true;
    try {
      const persist = remember && app.canRememberKeys;
      const saved = await app.backend.saveEndpoint(form.id, {
        base_url: form.base_url.trim(), capabilities: { ...form.caps },
        input_cost_per_mtok: Number(form.input) || 0, output_cost_per_mtok: Number(form.output) || 0,
        key: form.key.trim() || null,
      }, persist);
      message = `Endpoint ${saved.id} saved${saved.key === "missing" ? " without a key" : ""}. Its models are listed as ${saved.id}:<model>.`;
      reset();
      await Promise.all([load(), refresh({ models: true })]);
    } catch (error) {
      message = error instanceof Error ? error.message : String(error);
    } finally {
      busy = false;
    }
  }

  async function remove(id: string) {
    if (!app.backend) return;
    await app.backend.removeEndpoint(id);
    if (editing === id) reset();
    await Promise.all([load(), refresh({ models: true })]);
  }
</script>

<div class="card endpoints">
  <h3>OpenAI-compatible endpoints</h3>
  <p class="muted">
    Any server with the OpenAI chat API (vLLM, llama.cpp, LiteLLM, hosted gateways). Its models are listed from
    <code>&lt;base URL&gt;/models</code>. A key is sent only to its own endpoint and only over https (or to a local or
    private address).
    {#if app.mode === "local"}
      The local app saves endpoints to <code>configs/endpoints.local.yaml</code> without keys; a key entered here is held
      in memory for this session.
    {:else}
      In the browser the endpoint must allow this page's origin (CORS). Endpoints and keys stay in this tab unless you
      choose to remember them.
    {/if}
  </p>

  {#each endpoints as endpoint (endpoint.id)}
    {@const error = app.models?.unavailable?.[endpoint.id]}
    <div class="row">
      <span class="name"><strong>{endpoint.id}</strong></span>
      <code class="url" title={endpoint.base_url}>{endpoint.base_url}</code>
      <span class="pill" class:on={endpoint.key !== "missing"}>{endpoint.key === "env" ? "key from .env" : endpoint.key === "session" ? "key set" : "no key"}</span>
      <span class="muted">{error ? "unavailable" : `${models(endpoint.id)} models`}</span>
      <button onclick={() => edit(endpoint)}>Edit</button>
      <button onclick={() => remove(endpoint.id)}>Remove</button>
    </div>
    {#if error}<p class="note">{error} {endpointHint(error, app.mode)}</p>{/if}
  {/each}

  <form class="form" onsubmit={(e) => { e.preventDefault(); void save(); }}>
    <label>Name <input type="text" bind:value={form.id} disabled={!!editing} placeholder="gpu-box" autocomplete="off" /></label>
    <label class="wide">Base URL <input type="url" bind:value={form.base_url} placeholder="https://llm.example.com/v1" autocomplete="off" /></label>
    <label>API key <input type="password" bind:value={form.key} autocomplete="off"
      placeholder={editing ? "unchanged" : "optional"} aria-label="Endpoint API key" /></label>
    <fieldset class="caps">
      <legend>Its models support</legend>
      {#each CAPS as cap (cap.key)}<label><input type="checkbox" bind:checked={form.caps[cap.key]} /> {cap.label}</label>{/each}
    </fieldset>
    <label>$ in / Mtok <input type="number" min="0" step="any" bind:value={form.input} placeholder="0" /></label>
    <label>$ out / Mtok <input type="number" min="0" step="any" bind:value={form.output} placeholder="0" /></label>
    <div class="actions">
      <button class="primary" type="submit" disabled={!ready || busy}>{editing ? "Save" : "Add endpoint"}</button>
      {#if editing}<button type="button" onclick={reset}>Cancel</button>{/if}
    </div>
  </form>
  {#if idProblem || urlProblem || taken}<p class="error">{idProblem || urlProblem || `An endpoint named ${form.id} exists; edit it instead.`}</p>{/if}
  {#if app.mode === "browser" && app.canRememberKeys}
    <label class="remember"><input type="checkbox" bind:checked={remember} /> Remember this endpoint and its key on this
      device (stored unencrypted in this browser's local storage; leave off on shared computers)</label>
  {/if}
  {#if message}<p class="muted">{message}</p>{/if}
</div>

<style>
  .endpoints { margin-top: 12px; }
  .endpoints h3 { margin-top: 0; }
  .row { display: grid; grid-template-columns: 120px minmax(0, 1fr) 110px 110px auto auto; gap: 8px; align-items: center; margin: 6px 0; }
  .url { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .form { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 12px; align-items: end; }
  .form label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
  .form .wide { grid-column: span 2; }
  .caps { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 12px; border: 0; padding: 0; margin: 0; }
  .caps label { flex-direction: row; align-items: center; }
  .actions { display: flex; gap: 8px; }
  .remember { display: block; margin-top: 8px; }
  code { background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
  @media (max-width: 640px) {
    .row { grid-template-columns: 1fr 1fr; }
    .form { grid-template-columns: minmax(0, 1fr); }
    .form .wide { grid-column: auto; }
  }
</style>
