// REST client. The real backend wins wherever it exists; mock data fills in
// when ?mock=1, when the backend is unreachable, or when one route 404s.
import { mockHandle } from "./mock.js";
import { AuthError } from "./errors.js";

export { AuthError };

const params = new URLSearchParams(typeof location !== "undefined" ? location.search : "");
const state = {
  mockRest: params.get("mock") === "1",   // all REST from mock
  mockWs: params.get("mock") === "1",     // simulated call instead of /ws
  partial: false,                          // some routes fell back to mock
};
const listeners = new Set();
const emit = () => listeners.forEach((f) => f({ ...state }));
export const getMode = () => ({ ...state });
export const onMode = (f) => { listeners.add(f); return () => listeners.delete(f); };

async function raw(method, path, body) {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  const text = await res.text();
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  return { status: res.status, ok: res.ok, data, text };
}

// No usable backend: network error, or the dev proxy's empty 5xx.
const unreachable = (r) => r.status >= 502 || (r.status === 500 && r.data == null && !r.text);

/** Decide the mode once on load from GET /api/me. Returns {user} or null. */
export async function bootstrap() {
  if (state.mockRest) {
    try { return await mockHandle("GET", "/api/me"); } catch { return null; }
  }
  let r;
  try { r = await raw("GET", "/api/me"); } catch { r = null; }
  if (!r || unreachable(r)) {
    console.warn("[paisadost] backend unreachable, using mock mode");
    state.mockRest = true; state.mockWs = true; emit();
    try { return await mockHandle("GET", "/api/me"); } catch { return null; }
  }
  if (r.status === 404) {
    console.warn("[paisadost] /api routes missing, mocking REST (voice stays real)");
    state.mockRest = true; emit();
    try { return await mockHandle("GET", "/api/me"); } catch { return null; }
  }
  if (r.status === 401) return null;
  if (r.ok && r.data && r.data.user) return r.data;
  return null;
}

export async function api(method, path, body) {
  if (state.mockRest) return mockHandle(method, path, body);
  let r;
  try { r = await raw(method, path, body); } catch (e) { r = null; }
  if (!r || unreachable(r) || r.status === 404) {
    console.warn(`[paisadost] ${method} ${path} → mock (${r ? r.status : "network"})`);
    if (!state.partial) { state.partial = true; emit(); }
    return mockHandle(method, path, body);
  }
  if (r.status === 401) throw new AuthError((r.data && r.data.error) || "Not signed in");
  if (!r.ok) throw new Error((r.data && (r.data.error || r.data.detail)) || `HTTP ${r.status}`);
  return r.data;
}

/** Thrown for a 422 from /api/documents: code is password_required,
 *  password_wrong, unreadable or nothing_found. */
export class DocError extends Error {
  constructor(code, message) { super(message || code); this.name = "DocError"; this.code = code; }
}

/** POST /api/documents as multipart (file + optional password). */
export async function uploadDocument(file, password) {
  const viaMock = async () => {
    try { return await mockHandle("POST", "/api/documents", { name: file.name, size: file.size, password: password || "" }); }
    catch (e) { if (e.code) throw new DocError(e.code, e.message); throw e; }
  };
  if (state.mockRest) return viaMock();
  const fd = new FormData();
  fd.append("file", file);
  if (password) fd.append("password", password);
  let res, data = null, text = "";
  try {
    res = await fetch("/api/documents", { method: "POST", credentials: "same-origin", body: fd });
    text = await res.text();
    try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  } catch { res = null; }
  const r = res ? { status: res.status, ok: res.ok, data, text } : null;
  if (!r || unreachable(r) || r.status === 404) {
    console.warn(`[paisadost] POST /api/documents → mock (${r ? r.status : "network"})`);
    if (!state.partial) { state.partial = true; emit(); }
    return viaMock();
  }
  if (r.status === 401) throw new AuthError((data && data.error) || "Not signed in");
  if (r.status === 422 && data && data.error) throw new DocError(data.error, data.message);
  if (!r.ok) throw new DocError("failed", (data && (data.message || data.error || data.detail)) || `Upload failed (HTTP ${r.status})`);
  return data;
}

export const get = (p) => api("GET", p);
export const post = (p, b) => api("POST", p, b);
