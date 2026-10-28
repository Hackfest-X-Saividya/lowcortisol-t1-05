// API client for the Nishaan backend. Staff sessions use a JWT kept in sessionStorage
// (refreshed automatically on 401); witness calls pass their session token explicitly.
const BASE = import.meta.env.VITE_API_BASE || "/api/v1";
const STAFF_KEY = "nishaan.staff";

export class ApiError extends Error {
  constructor(status, code, message, body) {
    super(message);
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

function load() {
  try {
    return JSON.parse(sessionStorage.getItem(STAFF_KEY) || "null");
  } catch {
    return null;
  }
}

let staff = load();
const listeners = new Set();

export const auth = {
  get user() {
    return staff?.user || null;
  },
  get access() {
    return staff?.access || null;
  },
  set(data) {
    staff = data ? { access: data.access_token, refresh: data.refresh_token, user: data.user } : null;
    try {
      if (staff) sessionStorage.setItem(STAFF_KEY, JSON.stringify(staff));
      else sessionStorage.removeItem(STAFF_KEY);
    } catch {
      /* storage unavailable: keep in memory */
    }
    listeners.forEach((fn) => fn(staff?.user || null));
  },
  subscribe(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  async logout() {
    const rt = staff?.refresh;
    auth.set(null);
    if (rt) {
      try {
        await fetch(`${BASE}/auth/logout`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: rt }),
        });
      } catch {
        /* ignore */
      }
    }
  },
};

let refreshing = null;
async function tryRefresh() {
  if (!staff?.refresh) return false;
  refreshing ||= (async () => {
    try {
      const r = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: staff.refresh }),
      });
      if (!r.ok) {
        auth.set(null);
        return false;
      }
      auth.set(await r.json());
      return true;
    } finally {
      setTimeout(() => (refreshing = null), 0);
    }
  })();
  return refreshing;
}

export async function api(path, { method = "GET", body, form, token, raw = false } = {}) {
  const headers = {};
  const bearer = token ?? staff?.access;
  if (bearer) headers.Authorization = `Bearer ${bearer}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let r;
  try {
    r = await fetch(`${BASE}${path}`, { method, headers, body: payload });
  } catch (e) {
    throw new ApiError(0, "network", "The server could not be reached.", null);
  }
  if (r.status === 401 && token === undefined && staff?.refresh && !path.startsWith("/auth/")) {
    if (await tryRefresh()) return api(path, { method, body, form, token, raw });
  }
  if (raw) return r;
  const text = await r.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!r.ok) {
    const err = data && data.error ? data.error : {};
    let message = err.message || `HTTP ${r.status}`;
    if (r.status === 422 && err.details?.errors?.length) {
      message += ": " + err.details.errors.map((x) => `${x.loc?.slice(-1)[0]} ${x.msg}`).join("; ");
    }
    throw new ApiError(r.status, err.code || `http_${r.status}`, message, data);
  }
  return data;
}

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

/** Poll a 202 job until it finishes. Resolves with the job result, rejects on failure. */
export async function waitJob(jobId, { token, interval = 700, timeout = 240000, onProgress } = {}) {
  const start = Date.now();
  for (;;) {
    const j = await api(`/jobs/${jobId}`, { token });
    onProgress?.(j);
    if (j.status === "done") return j.result || {};
    if (j.status === "failed") throw new ApiError(500, "job_failed", j.error || "Job failed", j);
    if (Date.now() - start > timeout) throw new ApiError(504, "job_timeout", "This is taking too long.", j);
    await sleep(interval);
  }
}

/** Submit a 202 endpoint and wait for its job. */
export async function runJob(path, opts = {}) {
  const accepted = await api(path, { method: "POST", ...opts });
  return waitJob(accepted.job_id, { token: opts.token, onProgress: opts.onProgress });
}

const blobCache = new Map();

/** Fetch a protected file once and return an object URL (cached per file id). */
export async function fileUrl(fileId, token) {
  if (!fileId) return null;
  if (blobCache.has(fileId)) return blobCache.get(fileId);
  const r = await api(`/files/${fileId}`, { token, raw: true });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      msg = (await r.json()).error.message;
    } catch {
      /* ignore */
    }
    throw new ApiError(r.status, "file", msg, null);
  }
  const url = URL.createObjectURL(await r.blob());
  blobCache.set(fileId, url);
  return url;
}

/** Live session events over the WebSocket (proxied by Vite). Returns a close function. */
export function sessionEvents(sessionId, token, onEvent) {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  let ws;
  let closed = false;
  let retry = 0;
  const open = () => {
    ws = new WebSocket(`${proto}://${window.location.host}/ws/sessions/${sessionId}?token=${encodeURIComponent(token)}`);
    ws.onmessage = (m) => {
      try {
        onEvent(JSON.parse(m.data));
      } catch {
        /* ignore */
      }
    };
    ws.onopen = () => (retry = 0);
    ws.onclose = (e) => {
      if (closed || e.code === 4401 || e.code === 4403) return;
      retry = Math.min(retry + 1, 6);
      setTimeout(open, 500 * 2 ** retry);
    };
  };
  open();
  return () => {
    closed = true;
    ws?.close();
  };
}

// Witness tokens: handed from the officer's screen to the witness tab through localStorage
// (never through the URL), then kept only in that tab's sessionStorage.
const HANDOFF = (sid) => `nishaan.handoff.${sid}`;
const WITNESS = (sid) => `nishaan.witness.${sid}`;

export function handOffWitnessToken(sessionId, token) {
  localStorage.setItem(HANDOFF(sessionId), token);
}

export function takeWitnessToken(sessionId) {
  try {
    const handed = localStorage.getItem(HANDOFF(sessionId));
    if (handed) {
      localStorage.removeItem(HANDOFF(sessionId));
      sessionStorage.setItem(WITNESS(sessionId), handed);
      return handed;
    }
    return sessionStorage.getItem(WITNESS(sessionId));
  } catch {
    return null;
  }
}

export function storeWitnessToken(sessionId, token) {
  try {
    if (token) sessionStorage.setItem(WITNESS(sessionId), token);
    else sessionStorage.removeItem(WITNESS(sessionId));
  } catch {
    /* ignore */
  }
}
