<script lang="ts">
  // Preformatted text with a label and a copy button; long content scrolls inside the block.
  let { text, label = "", language = "", max = 420 }: { text: string; label?: string; language?: string; max?: number } = $props();
  let copied = $state(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      copied = false;
    }
  }
</script>

<figure class="code">
  {#if label || language}
    <figcaption>
      <span>{label}{language && label ? " · " : ""}<span class="muted">{language}</span></span>
      <button class="copy" onclick={copy} aria-label={`Copy ${label || "text"}`}>{copied ? "Copied" : "Copy"}</button>
    </figcaption>
  {/if}
  <pre style:max-height={`${max}px`}>{text || "—"}</pre>
</figure>

<style>
  .code { margin: 0; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: var(--surface-2); }
  figcaption { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 4px 8px; font-size: 12px;
    border-bottom: 1px solid var(--border); color: var(--text-secondary); }
  .copy { padding: 2px 8px; font-size: 12px; }
  pre { margin: 0; padding: 10px 12px; overflow: auto; font: 12.5px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
    white-space: pre-wrap; word-break: break-word; color: var(--text-primary); }
</style>
