<script lang="ts">
  // Accessible tab bar (WAI-ARIA tabs pattern): arrow keys move between tabs, Home/End jump; the parent owns
  // which tab is active (usually from the URL) and renders the panel with id `${id}-panel`.
  let { tabs, active, id, onselect }: {
    tabs: { key: string; label: string; count?: number }[]; active: string; id: string; onselect: (key: string) => void;
  } = $props();

  let list = $state<HTMLElement | null>(null);

  function onkeydown(event: KeyboardEvent) {
    const index = tabs.findIndex((t) => t.key === active);
    const next = event.key === "ArrowRight" ? index + 1 : event.key === "ArrowLeft" ? index - 1
      : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    const target = tabs[(next + tabs.length) % tabs.length]!;
    onselect(target.key);
    queueMicrotask(() => list?.querySelector<HTMLElement>(`#${id}-tab-${target.key}`)?.focus());
  }
</script>

<div class="tabs" role="tablist" aria-orientation="horizontal" bind:this={list} tabindex="-1" {onkeydown}>
  {#each tabs as tab (tab.key)}
    <button role="tab" id={`${id}-tab-${tab.key}`} aria-selected={tab.key === active} aria-controls={`${id}-panel`}
      tabindex={tab.key === active ? 0 : -1} class:active={tab.key === active} onclick={() => onselect(tab.key)}>
      {tab.label}{#if tab.count !== undefined}<span class="count">{tab.count}</span>{/if}
    </button>
  {/each}
</div>

<style>
  .tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--border); margin: 20px 0 16px; overflow-x: auto; }
  .tabs:focus { outline: none; }
  button { background: none; border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 10px 14px;
    color: var(--text-secondary); font-weight: 500; white-space: nowrap; }
  button:hover { color: var(--text-primary); }
  button.active { color: var(--text-primary); border-bottom-color: var(--accent); }
  button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .count { margin-left: 6px; font-size: 12px; color: var(--text-muted); background: var(--surface-2); border-radius: 999px; padding: 1px 7px; }
</style>
