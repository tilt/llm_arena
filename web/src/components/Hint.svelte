<script lang="ts">
  // A short explanation behind a small "?" button. Unlike a title tooltip it works with touch, the keyboard and screen
  // readers. It renders two siblings, so in a wrapping flex row the text opens on its own line below (never put it in
  // a <p>: the text is a block).
  import type { Snippet } from "svelte";

  let { label, children }: { label: string; children: Snippet } = $props();
  let open = $state(false);
  const id = $props.id();
</script>

<button type="button" class="hint" aria-label={label} title={label} aria-expanded={open} aria-controls={id}
  onclick={() => (open = !open)} onkeydown={(e) => { if (e.key === "Escape") open = false; }}>?</button>
<div {id} class="hint-text small" hidden={!open}><div class="body">{@render children()}</div></div>

<style>
  .hint { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; min-height: 20px;
    padding: 0; border-radius: 50%; border: 1px solid var(--axis); background: transparent; color: var(--text-secondary);
    font-size: 12px; font-weight: 600; line-height: 1; cursor: pointer; vertical-align: middle; }
  .hint[aria-expanded="true"] { background: var(--surface-2); color: var(--text-primary); }
  /* the full row, so a wrapping flex parent puts it on its own line; the width cap sits on the body inside */
  .hint-text { display: block; flex: 0 0 100%; margin: 6px 0; }
  .body { max-width: 640px; padding: 8px 12px; border-radius: 8px; background: var(--surface-2); color: var(--text-secondary); }
  .body :global(p) { margin: 0 0 4px; }
  .hint-text[hidden] { display: none; }
  /* a bigger target on touch, without changing how the icon looks */
  @media (pointer: coarse) { .hint { position: relative; } .hint::after { content: ""; position: absolute; inset: -12px; } }
</style>
