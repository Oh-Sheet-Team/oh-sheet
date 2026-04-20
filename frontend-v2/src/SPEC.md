# frontend-v2 module spec

Shared contract between `api.js`, `state.js`, and `views.js`. Agents
working on each module MUST keep to these interfaces so integration
is a no-op at the end.

## Backend endpoints we call

All on same-origin (`/v1/*`), proxied to oh-sheet backend in dev.

### `POST /v1/uploads/audio`
Multipart form upload. `file` field = audio bytes (mp3/wav/flac/m4a).
Returns `{ "audio": RemoteAudioFile }`.

### `POST /v1/uploads/midi`
Multipart form upload. `file` field = MIDI bytes (.mid/.midi).
Returns `{ "midi": RemoteMidiFile }`.

### `POST /v1/jobs`
JSON body: one of
- `{ audio: RemoteAudioFile, title?, artist? }` — source=audio_upload
- `{ midi: RemoteMidiFile, title?, artist? }` — source=midi_upload
- `{ title: string, artist?: string, prefer_clean_source?: bool }` — source=title_lookup
Returns `{ job_id, status, variant, title, artist, result, error }`.

### `GET /v1/jobs/:id`
Returns the same job shape. Use for polling or refetch after WS event.

### `WS /v1/jobs/:id/ws`
Server streams `JobEvent` objects as they fire. Shape:
```
{ job_id, type: "stage_started"|"stage_completed"|"job_succeeded"|"job_failed",
  stage: "ingest"|"transcribe"|"arrange"|"humanize"|"engrave",
  progress: 0..1, message?, data? }
```

### `GET /v1/artifacts/:id/:kind`
`kind ∈ {pdf, midi, musicxml}` — returns the file directly.

## TypeScript-ish types (used as JSDoc)

```
type SourceType = "audio" | "midi" | "title" | "youtube"

type JobResult = {
  schema_version: string,
  metadata: { title, composer, ... },
  pdf_uri: string|null,
  musicxml_uri: string,
  humanized_midi_uri: string,
  tunechat_job_id: string|null,
  tunechat_preview_image_url: string|null,
}

type Phase =
  | { name: "idle", source: SourceType }
  | { name: "submitting" }
  | { name: "working", stage: "ingest"|"transcribe"|"arrange"|"engrave", progress: number }
  | { name: "complete", job: JobWithResult }
  | { name: "error", message: string, retryable: boolean }
```

## Module: `api.js`

Exports (pure HTTP layer, no DOM):

```
uploadAudio(file: File): Promise<RemoteAudioFile>
uploadMidi(file: File): Promise<RemoteMidiFile>
createJob(payload): Promise<Job>
getJob(jobId): Promise<Job>
subscribeToJob(jobId, onEvent): () => void  // returns unsubscribe fn
artifactUrl(jobId, kind): string            // just builds the URL
```

## Module: `state.js`

Exports:

```
createStore(initial?): {
  getPhase(): Phase,
  setPhase(phase): void,
  onChange(cb: (phase) => void): () => void,  // unsubscribe
}

// Pure reducer for backend events → next phase
reduceJobEvent(phase: Phase, event: JobEvent): Phase

// Derived helpers for the view layer
stageOrder(): ["ingest", "transcribe", "arrange", "engrave"]
stageLabel(stage): string                    // "Transcribing..." etc
```

## Module: `views.js`

Exports:

```
renderPhase(container: HTMLElement, phase: Phase, handlers): void
// handlers = { onSubmit(formData), onRetry(), onSourceChange(source) }
```

Each phase renders into the given container (body of the morphing card).
Replaces innerHTML via `container.replaceChildren(...)` — no framework.

The mascot above the card is managed by the app shell, not the phase
renderer — views.js just returns the semantic card body.

## Bootstrap (`main.js`)

Responsibilities:
1. Grab `#card` container
2. Create store with initial phase = `{ name: "idle", source: "youtube" }`
3. Subscribe to store → call `views.renderPhase()` on every change, also
   update the mascot src per phase
4. Wire handlers:
   - `onSourceChange` → `store.setPhase({ name: "idle", source })`
   - `onSubmit(formData)` → upload if needed, POST /v1/jobs, open WS,
     transition to Submitting then Working
5. Open WS subscription on job creation, pipe events through
   `reduceJobEvent`
