// Pure state management for the oh-sheet card-morph UI.
// No DOM, no framework — just a tiny pub/sub store plus a pure reducer.

const DEFAULT_INITIAL = { name: "idle", source: "youtube" };

export function createStore(initial = DEFAULT_INITIAL) {
  let phase = initial;
  const subscribers = new Set();

  return {
    getPhase() {
      return phase;
    },
    setPhase(next) {
      phase = next;
      for (const cb of subscribers) cb(phase);
    },
    onChange(cb) {
      subscribers.add(cb);
      return () => subscribers.delete(cb);
    },
  };
}

const STAGES = ["ingest", "transcribe", "arrange", "engrave"];

const STAGE_LABELS = {
  ingest: "Preparing",
  transcribe: "Transcribing",
  arrange: "Arranging",
  engrave: "Engraving",
};

export function stageOrder() {
  return [...STAGES];
}

export function stageLabel(stage) {
  return STAGE_LABELS[stage] ?? "";
}

// Pure reducer: (phase, event) -> next phase. Never mutates inputs.
export function reduceJobEvent(phase, event) {
  switch (event.type) {
    case "stage_started": {
      if (!STAGES.includes(event.stage)) return phase;
      return {
        name: "working",
        stage: event.stage,
        progress: event.progress ?? 0,
      };
    }
    case "stage_completed": {
      // Keep the current stage; bump progress. If we're somehow not in
      // "working" yet, fall into working using the event's stage.
      const stage =
        phase.name === "working" ? phase.stage : event.stage;
      if (!STAGES.includes(stage)) return phase;
      return {
        name: "working",
        stage,
        progress: event.progress ?? (phase.progress ?? 0),
      };
    }
    case "job_succeeded": {
      return { name: "complete", job: event.data };
    }
    case "job_failed": {
      return {
        name: "error",
        message: event.message ?? "Job failed",
        retryable: true,
      };
    }
    default:
      return phase;
  }
}
