// Same-origin by default (the packaged exe serves UI + API from one
// FastAPI process). Dev falls back to :8000; override via NEXT_PUBLIC_*.
const _envApi = process.env.NEXT_PUBLIC_API_URL;
const _sameOrigin =
  typeof window !== "undefined" ? window.location.origin : "http://localhost:8000";

export const API_URL =
  _envApi ?? (typeof window !== "undefined" && window.location.port !== "3000"
    ? "" // served by the same server -> relative URLs
    : "http://localhost:8000");

export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ??
  (typeof window !== "undefined" && window.location.port !== "3000"
    ? _sameOrigin.replace(/^http/, "ws") + "/ws"
    : "ws://localhost:8000/ws");

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function apiSend<T>(
  path: string,
  body: unknown,
  method: "POST" | "PATCH" = "POST",
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${detail.slice(0, 200)}`);
  }
  return res.json();
}
