import type { CallEvent, Config, Line, Scenario } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Called when the server says the sign-in is gone (expired, signed out, or access removed). */
let onSignedOut: () => void = () => undefined;
export function whenSignedOut(fn: () => void) {
  onSignedOut = fn;
}

// The sign-in lives in an HttpOnly cookie the browser sends by itself; scripts never see it.
async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...init, headers, credentials: "same-origin" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && path !== "/api/login") onSignedOut();
    throw new ApiError(res.status, body.error ?? `Request failed (${res.status})`);
  }
  return body as T;
}

export interface CallHandle {
  call_id: string;
  token: string;
  line: Line;
}

export const api = {
  config: () => request<Config>("/api/config"),
  login: (userId: string, password: string) =>
    request<{ user: string }>("/api/login", { method: "POST", body: JSON.stringify({ user_id: userId, password }) }),
  logout: () => request("/api/logout", { method: "POST" }),
  scenarios: () => request<{ scenarios: Scenario[] }>("/api/scenarios").then((r) => r.scenarios),
  startCall: (line: Line, scenarioId?: string) =>
    request<CallHandle>("/api/calls", { method: "POST", body: JSON.stringify({ line, scenario_id: scenarioId ?? null }) }),
  say: (call: CallHandle, text: string) =>
    request<{ reply: string; ended: boolean; verified: boolean; locked: boolean }>(
      `/api/calls/${call.call_id}/turn`, { method: "POST", body: JSON.stringify({ text }) }, call.token),
  hangUp: (call: CallHandle) => request(`/api/calls/${call.call_id}/end`, { method: "POST" }, call.token),
};

/** Subscribe to a call's live events. Returns a function that closes the stream. */
export function streamEvents(call: CallHandle, onEvent: (e: CallEvent) => void, onClose: () => void): () => void {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/api/calls/${call.call_id}/events`);
  ws.onopen = () => ws.send(JSON.stringify({ token: call.token }));
  ws.onmessage = (m) => {
    try {
      onEvent(JSON.parse(m.data));
    } catch {
      /* ignore malformed frames */
    }
  };
  ws.onclose = onClose;
  return () => ws.close();
}
