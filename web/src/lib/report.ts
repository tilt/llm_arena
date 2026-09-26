// Shape a RunBundle into what the report views render. Pure, so it is unit-tested.
import type { ConfigSummary, PairedTest, RunBundle } from "./contracts";

export interface ScenarioSection {
  scenario: string;
  pattern: string;
  configs: ConfigSummary[]; // best first
  e2eMetrics: string[];
  stepMetrics: string[]; // rates in [0, 1] -> heatmap; the table shows all
  rateMetrics: string[];
  derivedMetrics: string[];
  tests: PairedTest[];
}

export interface Bar {
  label: string;
  value: number;
  low: number;
  high: number;
  n: number;
}

export function bars(section: ScenarioSection): Bar[] {
  return section.configs.map((c) => ({ label: c.config, value: c.pass_rate, low: c.ci_low, high: c.ci_high, n: c.trials }));
}

export interface Matrix {
  rows: string[];
  columns: string[];
  values: (number | null)[][];
}

const keysOf = (configs: ConfigSummary[], pick: (c: ConfigSummary) => Record<string, number | undefined> | undefined) =>
  [...new Set(configs.flatMap((c) => Object.keys(pick(c) ?? {})))].sort();

export function sections(bundle: RunBundle): ScenarioSection[] {
  const byScenario = new Map<string, ConfigSummary[]>();
  for (const config of bundle.summary.configs) {
    byScenario.set(config.scenario, [...(byScenario.get(config.scenario) ?? []), config]);
  }
  return [...byScenario.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([scenario, configs]) => {
      const stepMetrics = keysOf(configs, (c) => c.step_means);
      return {
        scenario,
        pattern: configs[0]?.pattern ?? "",
        configs: [...configs].sort((a, b) => b.pass_rate - a.pass_rate),
        e2eMetrics: keysOf(configs, (c) => c.e2e_means),
        stepMetrics,
        rateMetrics: stepMetrics.filter((m) => configs.every((c) => isRate(c.step_means?.[m]))),
        derivedMetrics: keysOf(configs, (c) => c.derived),
        tests: bundle.summary.paired_tests.filter((t) => t.scenario === scenario),
      };
    });
}

export function passRateMatrix(bundle: RunBundle): Matrix {
  const configs = bundle.summary.configs;
  const rows = [...new Set(configs.map((c) => c.config))].sort();
  const columns = [...new Set(configs.map((c) => c.scenario))].sort();
  const lookup = new Map(configs.map((c) => [`${c.config}|${c.scenario}`, c.pass_rate]));
  return { rows, columns, values: rows.map((r) => columns.map((c) => finite(lookup.get(`${r}|${c}`)))) };
}

export function stepMatrix(section: ScenarioSection): Matrix {
  return {
    rows: section.configs.map((c) => c.config),
    columns: section.rateMetrics,
    values: section.configs.map((c) => section.rateMetrics.map((m) => finite(c.step_means?.[m]))),
  };
}

export function ratings(bundle: RunBundle): { scope: string; ranking: [string, number][] }[] {
  return Object.entries(bundle.summary.ratings)
    .map(([scope, values]) => ({
      scope,
      ranking: (Object.entries(values ?? {}).filter(([, v]) => v !== undefined) as [string, number][]).sort((a, b) => b[1] - a[1]),
    }))
    .sort((a, b) => (a.scope === "overall" ? -1 : b.scope === "overall" ? 1 : a.scope.localeCompare(b.scope)));
}

export interface TrialRow {
  trial_id: string;
  scenario: string;
  config: string;
  task_id: string;
  repeat: number;
  status: string;
  passed: boolean;
  duration_s: number;
  tokens: number;
  error: string | null;
  final: string;
}

export function trials(bundle: RunBundle): TrialRow[] {
  return bundle.trials.map((t) => ({
    trial_id: String(t.trial_id),
    scenario: String(t.scenario),
    config: String(t.config),
    task_id: String(t.task_id),
    repeat: Number(t.repeat),
    status: String(t.status),
    passed: Boolean(t.passed),
    duration_s: Number(t.duration_s),
    tokens: Number(t.prompt_tokens ?? 0) + Number(t.completion_tokens ?? 0),
    error: t.error ? String(t.error) : null,
    final: String(t.final ?? ""),
  }));
}

export function isRate(value: number | null | undefined): boolean {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

function finite(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
