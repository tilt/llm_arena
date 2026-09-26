// Fold run events into the state the run monitor shows.
import type { RunEvent, TrialFinished } from "./contracts";

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
}

export const initialProgress: RunProgress = {
  total: 0, done: 0, passed: 0, failed: 0, errors: 0, spentUsd: 0, running: [], recent: [],
  finished: false, stoppedEarly: false, budgetHit: false,
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
      return { ...state, budgetHit: true };
    case "run_finished":
      return { ...state, finished: true, stoppedEarly: event.stopped_early, spentUsd: event.spent_usd, running: [] };
    default:
      return state; // unknown event types from a newer engine are ignored
  }
}
