<script lang="ts">
  import type { Workflow } from "../lib/contracts";
  import type { StepStats } from "../lib/inspect";
  import { NODE_H, NODE_W, layout, stepRoles } from "../lib/workflow";

  // `models`: role -> what runs it (model ref, "same as critic", "rules", "ollaya winnow:e4b", …).
  // With `stats` + `onselect` the diagram is a run map: steps show how often they ran and can be selected.
  let {
    flow, models = {}, highlight = $bindable(""), label = "Workflow", stats, selected = "", onselect,
  }: {
    flow: Workflow; models?: Record<string, string>; highlight?: string; label?: string;
    stats?: Record<string, StepStats>; selected?: string; onselect?: (step: string) => void;
  } = $props();
  const interactive = $derived(!!onselect);
  const ran = (id: string) => !stats || (stats[id]?.runs ?? 0) > 0 || id === "start";
  function key(event: KeyboardEvent, id: string) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onselect?.(id);
    }
  }

  const placed = $derived(layout(flow));
  const KIND_LABEL: Record<string, string> = {
    llm: "model", tool: "tools", code: "sandbox", check: "check", decision: "decision", human: "human", start: "", end: "",
  };
  const short = (text: string, max = 30) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);
</script>

<div class="wrap" role="group" aria-label={label}>
  <svg viewBox={`-4 -4 ${placed.width + 8} ${placed.height + 8}`} width={placed.width + 8} height={placed.height + 8}>
    <defs>
      <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M0,0 L10,5 L0,10 z" class="arrowhead" />
      </marker>
    </defs>
    {#each placed.edges as e, i (i)}
      <path d={e.path} class="edge" class:loop={e.edge.loop} marker-end="url(#arrow)" />
      {#if e.edge.label}
        <text x={e.labelX} y={e.labelY} class="edge-label" text-anchor={e.anchor} dy="-3">{e.edge.label}</text>
      {/if}
    {/each}
    {#each placed.steps as p (p.step.id)}
      {@const roles = stepRoles(p.step)}
      {@const lit = !!highlight && roles.includes(highlight)}
      {@const s = stats?.[p.step.id]}
      <g transform={`translate(${p.x},${p.y})`} class={`node kind-${p.step.kind}`} class:lit class:interactive
        class:selected={selected === p.step.id} class:idle={!ran(p.step.id)} class:failed={!!s?.errors}
        role="button" tabindex="0" data-step={p.step.id} aria-pressed={interactive ? selected === p.step.id : undefined}
        aria-label={`${p.step.label}${p.step.role ? `, runs on ${models[p.step.role] ?? p.step.role}` : ""}${stats ? `, ran ${s?.runs ?? 0} times${s?.errors ? `, ${s.errors} errors` : ""}` : ""}`}
        onclick={() => onselect?.(p.step.id)} onkeydown={(e) => key(e, p.step.id)}
        onmouseenter={() => (highlight = p.step.role ?? "")} onmouseleave={() => (highlight = "")}
        onfocus={() => (highlight = p.step.role ?? "")} onblur={() => (highlight = "")}>
        <title>{p.step.label}{p.step.description ? `: ${p.step.description}` : ""}</title>
        {#if p.step.kind === "start" || p.step.kind === "end"}
          <rect x={NODE_W / 2 - 50} y={NODE_H / 2 - 16} width="100" height="32" rx="16" class="terminal" />
          <text x={NODE_W / 2} y={NODE_H / 2 + 5} text-anchor="middle" class="title">{p.step.label}</text>
        {:else}
          <rect width={NODE_W} height={NODE_H} rx="9" class="box" />
          <rect width="5" height={NODE_H} rx="2" class="stripe" />
          <text x="14" y="18" class="kind">{KIND_LABEL[p.step.kind]}{p.step.role ? ` · ${p.step.role}` : ""}</text>
          <text x="14" y="35" class="title">{short(p.step.label)}</text>
          {#if stats && ran(p.step.id)}
            <g transform={`translate(${NODE_W - 34},-9)`} class="badge"><rect width="40" height="18" rx="9" /><text x="20" y="13" text-anchor="middle">{s?.errors ? "! " : ""}×{s?.runs ?? 0}</text></g>
          {/if}
          {#if p.step.role && models[p.step.role]}
            <text x="14" y="50" class="model">{short(models[p.step.role]!, 32)}</text>
          {:else if p.step.description}
            <text x="14" y="50" class="desc">{short(p.step.description, 32)}</text>
          {/if}
        {/if}
      </g>
    {/each}
  </svg>
</div>

<style>
  .wrap { overflow-x: auto; max-width: 100%; }
  svg { display: block; margin: 0 auto; font-family: inherit; }
  .edge { fill: none; stroke: var(--axis); stroke-width: 1.5; }
  .edge.loop { stroke-dasharray: 4 3; }
  .arrowhead { fill: var(--axis); }
  .edge-label { font-size: 11px; fill: var(--text-muted); paint-order: stroke; stroke: var(--page); stroke-width: 3px; }
  .box { fill: var(--surface-1); stroke: var(--border); }
  .terminal { fill: var(--surface-2); stroke: var(--border); }
  .node { outline: none; cursor: default; }
  .node.lit .box, .node:focus-visible .box { stroke: var(--accent); stroke-width: 2; }
  .node.interactive { cursor: pointer; }
  .node.selected .box { stroke: var(--accent); stroke-width: 2.5; fill: var(--surface-2); }
  .node.idle { opacity: 0.45; }
  .node.failed .box { stroke: var(--critical); }
  .badge rect { fill: var(--surface-3); stroke: var(--border); }
  .badge text { font-size: 11px; fill: var(--text-secondary); font-variant-numeric: tabular-nums; }
  .node.failed .badge text { fill: var(--critical); }
  .stripe { fill: var(--accent); }
  .kind-tool .stripe { fill: var(--kind-tool); }
  .kind-code .stripe { fill: var(--kind-code); }
  .kind-decision .stripe { fill: var(--kind-decision); }
  .kind-human .stripe { fill: var(--kind-human); }
  .kind-check .stripe { fill: var(--kind-check); }
  .kind { font-size: 10.5px; fill: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .title { font-size: 13px; font-weight: 600; fill: var(--text-primary); }
  .model { font-size: 11.5px; fill: var(--accent); }
  .desc { font-size: 11.5px; fill: var(--text-secondary); }
</style>
