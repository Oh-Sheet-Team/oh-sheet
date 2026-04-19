// Pure HTTP/WS layer for the oh-sheet backend. No DOM, no state.
// All endpoints are same-origin (`/v1/*`), proxied in dev via vite.config.js.

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024; // 50 MB

/**
 * Parse an error out of a non-2xx fetch Response. Prefers the server's
 * JSON `error` field, falls back to status text so the user never sees
 * a bare "500" with no context.
 */
async function extractError(response) {
  try {
    const body = await response.json();
    if (body && typeof body.error === "string" && body.error.length > 0) {
      return new Error(body.error);
    }
    if (body && typeof body.message === "string" && body.message.length > 0) {
      return new Error(body.message);
    }
  } catch {
    // fall through to status text
  }
  return new Error(response.statusText || `HTTP ${response.status}`);
}

function assertUnderSizeLimit(file) {
  if (file && typeof file.size === "number" && file.size > MAX_UPLOAD_BYTES) {
    throw new Error("File exceeds 50 MB upload limit");
  }
}

async function postMultipart(url, file, responseKey) {
  assertUnderSizeLimit(file);
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(url, { method: "POST", body: form });
  if (!response.ok) throw await extractError(response);
  const body = await response.json();
  return body[responseKey];
}

export async function uploadAudio(file) {
  return postMultipart("/v1/uploads/audio", file, "audio");
}

export async function uploadMidi(file) {
  return postMultipart("/v1/uploads/midi", file, "midi");
}

export async function createJob(payload) {
  const response = await fetch("/v1/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await extractError(response);
  return response.json();
}

export async function getJob(jobId) {
  const response = await fetch(`/v1/jobs/${jobId}`);
  if (!response.ok) throw await extractError(response);
  return response.json();
}

/**
 * Build a WS URL from the current page origin so the socket hits the same
 * host/port as the API (and the vite proxy in dev).
 */
function buildWsUrl(path) {
  if (typeof window !== "undefined" && window.location) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}${path}`;
  }
  return path;
}

export function subscribeToJob(jobId, onEvent) {
  const ws = new WebSocket(buildWsUrl(`/v1/jobs/${jobId}/ws`));
  ws.onmessage = (ev) => {
    try {
      const parsed = JSON.parse(ev.data);
      onEvent(parsed);
    } catch {
      // Ignore malformed frames — server should never send non-JSON.
    }
  };
  return () => {
    try {
      ws.close();
    } catch {
      // no-op
    }
  };
}

export function artifactUrl(jobId, kind) {
  return `/v1/artifacts/${jobId}/${kind}`;
}
