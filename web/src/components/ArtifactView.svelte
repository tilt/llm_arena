<script lang="ts">
  import { app } from "../lib/app.svelte";
  import type { ArtifactRef } from "../lib/contracts";
  import CodeBlock from "./CodeBlock.svelte";

  // One stored file of a step: images inline, JSON/text as a code block, anything else as a download.
  let { runId, artifact }: { runId: string; artifact: ArtifactRef } = $props();

  let url = $state<string | null>(null);
  let body = $state("");
  let failed = $state(false);
  const isImage = $derived(artifact.media_type.startsWith("image/"));
  const isText = $derived(artifact.media_type.startsWith("text/") || artifact.media_type.includes("json"));
  const size = $derived(artifact.size > 1024 * 1024 ? `${(artifact.size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(artifact.size / 1024))} KB`);

  $effect(() => {
    url = null; body = ""; failed = false;
    if (!artifact.key || !app.backend) return;
    app.backend.artifactUrl(runId, artifact.key).then(async (found) => {
      url = found;
      if (found && isText) {
        const text = await (await fetch(found)).text();
        try { body = JSON.stringify(JSON.parse(text), null, 2); } catch { body = text; }
      }
    }, () => (failed = true));
  });
</script>

<div class="artifact">
  {#if !artifact.key}
    <p class="muted small">{artifact.name} ({size}): {artifact.note || "not stored"}</p>
  {:else if failed}
    <p class="note small">Could not load {artifact.name}.</p>
  {:else if !url}
    <div class="placeholder" aria-busy="true">Loading {artifact.name}…</div>
  {:else if isImage}
    <a href={url} target="_blank" rel="noopener" title="Open full size">
      <img src={url} alt={`${artifact.name} produced or used by this step`} loading="lazy" />
    </a>
    <p class="muted small">{artifact.name} · {size}</p>
  {:else if isText}
    <CodeBlock text={body} label={artifact.name} language={artifact.media_type.includes("json") ? "json" : ""} />
  {:else}
    <a href={url} download={artifact.name}>Download {artifact.name}</a> <span class="muted small">{size}</span>
  {/if}
</div>

<style>
  .artifact img { display: block; max-width: 100%; max-height: 420px; border-radius: 8px; border: 1px solid var(--border); background: #fff; }
  .placeholder { height: 120px; border-radius: 8px; background: var(--surface-2); display: grid; place-items: center; color: var(--text-muted); font-size: 13px; }
  .small { font-size: 12px; margin: 4px 0 0; }
</style>
