// Fold run events into the state the run monitor shows.
import type { RunEvent, TrialFinished } from "./contracts";
import { usd } from "./format";

export interface RunProgress {
  total: number;
  done: number;
  passed: number;
  failed: number;
  errors: number;
  spentUsd: number;
  running: string[]; // "scenario / config / task"
  recent: TrialFinished[];
  finished: boolean;
  stoppedEarly: boolean;
  budgetHit: boolean;
  limitUsd: number | null; // the spend limit that stopped the run, from budget_exceeded
  warnings: string[];
}

export const initialProgress: RunProgress = {
  total: 0, done: 0, passed: 0, failed: 0, errors: 0, spentUsd: 0, running: [], recent: [],
  finished: false, stoppedEarly: false, budgetHit: false, limitUsd: null, warnings: [],
};

const label = (e: { scenario: string; config: string; task_id: string; repeat: number }) =>
  `${e.scenario} / ${e.config} / ${e.task_id}${e.repeat ? ` #${e.repeat}` : ""}`;

export function reduce(state: RunProgress, event: RunEvent): RunProgress {
  switch (event.type) {
    case "run_started":
      return { ...state, total: event.pending };
    case "trial_started":
      return { ...state, running: [...state.running, label(event)] };
    case "trial_finished":
      return {
        ...state,
        done: state.done + 1,
        passed: state.passed + (event.passed ? 1 : 0),
        failed: state.failed + (!event.passed && event.status === "ok" ? 1 : 0),
        errors: state.errors + (event.status === "ok" ? 0 : 1),
        spentUsd: state.spentUsd + event.cost_usd,
        running: state.running.filter((r) => r !== label(event)),
        recent: [event, ...state.recent].slice(0, 50),
      };
    case "budget_exceeded":
      return { ...state, budgetHit: true, limitUsd: event.limit_usd };
    case "run_warning":
      return { ...state, warnings: [...state.warnings, event.message] };
    case "run_finished":
      return { ...state, finished: true, stoppedEarly: event.stopped_early, spentUsd: event.spent_usd, running: [] };
    default:
      return state; // unknown event types from a newer engine are ignored
  }
}

/** Why a finished run stopped before all its trials ran, or null when it ran to the end. */
export function stopReason(state: RunProgress): string | null {
  if (!state.finished || !state.stoppedEarly) return null;
  if (!state.budgetHit || state.limitUsd === null) return "The run stopped early: it was cancelled.";
  if (state.limitUsd === 0) {
    return "The run stopped early: a paid model was called, but the spend limit is $0.00, which runs free models only. Raise the limit to run paid models.";
  }
  return `The run stopped early at its spend limit: ${usd(state.spentUsd)} spent of ${usd(state.limitUsd)}. Raise the limit to run every trial.`;
}
