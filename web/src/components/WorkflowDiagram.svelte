<script lang="ts">
  import type { Workflow } from "../lib/contracts";
  import { NODE_H, NODE_W, layout, stepRoles } from "../lib/workflow";

  // `models`: role -> what runs it (model ref, "same as critic", "rules", "ollaya winnow:e4b", …).
  let {
    flow, models = {}, highlight = $bindable(""), label = "Workflow",
  }: { flow: Workflow; models?: Record<string, string>; highlight?: string; label?: string } = $props();

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
        <text x={e.labelX} y={e.labelY} class="edge-label" text-anchor={e.edge.loop ? "start" : "middle"} dy="-3">{e.edge.label}</text>
      {/if}
    {/each}
    {#each placed.steps as p (p.step.id)}
      {@const roles = stepRoles(p.step)}
      {@const lit = !!highlight && roles.includes(highlight)}
      <g transform={`translate(${p.x},${p.y})`} class={`node kind-${p.step.kind}`} class:lit
        role="button" tabindex="0" aria-label={`${p.step.label}${p.step.role ? `, runs on ${models[p.step.role] ?? p.step.role}` : ""}`}
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
          {#if p.step.role}
            <text x="14" y="50" class="model">{short(models[p.step.role] ?? "—", 32)}</text>
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
