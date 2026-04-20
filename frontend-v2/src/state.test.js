import { describe, it, expect, vi } from "vitest";
import {
  createStore,
  reduceJobEvent,
  stageOrder,
  stageLabel,
} from "./state.js";

describe("createStore", () => {
  it("defaults initial phase to idle/youtube", () => {
    const store = createStore();
    expect(store.getPhase()).toEqual({ name: "idle", source: "youtube" });
  });

  it("accepts a custom initial phase", () => {
    const initial = { name: "idle", source: "audio" };
    const store = createStore(initial);
    expect(store.getPhase()).toEqual(initial);
  });

  it("setPhase updates the current phase", () => {
    const store = createStore();
    store.setPhase({ name: "submitting" });
    expect(store.getPhase()).toEqual({ name: "submitting" });
  });

  it("onChange subscribers fire on every setPhase", () => {
    const store = createStore();
    const cb = vi.fn();
    store.onChange(cb);
    store.setPhase({ name: "submitting" });
    store.setPhase({ name: "working", stage: "ingest", progress: 0 });
    expect(cb).toHaveBeenCalledTimes(2);
    expect(cb).toHaveBeenLastCalledWith({
      name: "working",
      stage: "ingest",
      progress: 0,
    });
  });

  it("onChange returns an unsubscribe fn that stops calls", () => {
    const store = createStore();
    const cb = vi.fn();
    const unsub = store.onChange(cb);
    store.setPhase({ name: "submitting" });
    unsub();
    store.setPhase({ name: "error", message: "x", retryable: true });
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it("multiple subscribers all fire on one change", () => {
    const store = createStore();
    const a = vi.fn();
    const b = vi.fn();
    const c = vi.fn();
    store.onChange(a);
    store.onChange(b);
    store.onChange(c);
    store.setPhase({ name: "submitting" });
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
    expect(c).toHaveBeenCalledTimes(1);
  });
});

describe("reduceJobEvent", () => {
  it("stage_started from submitting → working with stage/progress", () => {
    const phase = { name: "submitting" };
    const event = {
      type: "stage_started",
      stage: "ingest",
      progress: 0,
    };
    expect(reduceJobEvent(phase, event)).toEqual({
      name: "working",
      stage: "ingest",
      progress: 0,
    });
  });

  it("stage_started from working transitions to new stage", () => {
    const phase = { name: "working", stage: "ingest", progress: 1 };
    const event = {
      type: "stage_started",
      stage: "transcribe",
      progress: 0,
    };
    expect(reduceJobEvent(phase, event)).toEqual({
      name: "working",
      stage: "transcribe",
      progress: 0,
    });
  });

  it.each([["ingest"], ["transcribe"], ["arrange"], ["engrave"]])(
    "stage_started handles stage=%s",
    (stage) => {
      const next = reduceJobEvent(
        { name: "submitting" },
        { type: "stage_started", stage, progress: 0.1 }
      );
      expect(next).toEqual({ name: "working", stage, progress: 0.1 });
    }
  );

  it("stage_completed updates progress, keeps stage", () => {
    const phase = { name: "working", stage: "transcribe", progress: 0.3 };
    const event = {
      type: "stage_completed",
      stage: "transcribe",
      progress: 1,
    };
    expect(reduceJobEvent(phase, event)).toEqual({
      name: "working",
      stage: "transcribe",
      progress: 1,
    });
  });

  it("job_succeeded → complete with job payload", () => {
    const phase = { name: "working", stage: "engrave", progress: 1 };
    const job = { job_id: "abc", result: { musicxml_uri: "/x.xml" } };
    const event = { type: "job_succeeded", data: job };
    expect(reduceJobEvent(phase, event)).toEqual({
      name: "complete",
      job,
    });
  });

  it("job_failed → error with message and retryable=true", () => {
    const phase = { name: "working", stage: "ingest", progress: 0 };
    const event = { type: "job_failed", message: "boom" };
    expect(reduceJobEvent(phase, event)).toEqual({
      name: "error",
      message: "boom",
      retryable: true,
    });
  });

  it("is pure — does not mutate input phase", () => {
    const phase = { name: "working", stage: "ingest", progress: 0.2 };
    const snapshot = JSON.parse(JSON.stringify(phase));
    reduceJobEvent(phase, {
      type: "stage_started",
      stage: "transcribe",
      progress: 0,
    });
    expect(phase).toEqual(snapshot);
  });

  it("is deterministic — same inputs give same outputs", () => {
    const phase = { name: "submitting" };
    const event = { type: "stage_started", stage: "arrange", progress: 0.5 };
    const a = reduceJobEvent(phase, event);
    const b = reduceJobEvent(phase, event);
    expect(a).toEqual(b);
  });
});

describe("stageOrder", () => {
  it("returns the 4 stages in order", () => {
    expect(stageOrder()).toEqual([
      "ingest",
      "transcribe",
      "arrange",
      "engrave",
    ]);
  });
});

describe("stageLabel", () => {
  it("returns user-facing labels for each stage", () => {
    expect(stageLabel("ingest")).toBe("Preparing");
    expect(stageLabel("transcribe")).toBe("Transcribing");
    expect(stageLabel("arrange")).toBe("Arranging");
    expect(stageLabel("engrave")).toBe("Engraving");
  });
});
