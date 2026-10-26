let csrf = "";
let workspace = localStorage.getItem("sp-workspace") || "";
export function configureSession(token: string) {
  csrf = token;
}
export function selectWorkspace(id: string) {
  workspace = id;
  localStorage.setItem("sp-workspace", id);
}
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  if (workspace) headers.set("X-Workspace-ID", workspace);
  const response = await fetch("/api/v1" + path, {
    ...options,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const message =
      typeof data.detail === "string"
        ? data.detail
        : data.error?.message || "Request failed. Please try again.";
    throw new ApiError(response.status, message);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const post = <T>(path: string, body: unknown, key?: string) =>
  api<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: key ? { "Idempotency-Key": key } : {},
  });
export function sourceUrl(id: string, version: number) {
  return `/api/v1/documents/${id}/source?workspace_id=${encodeURIComponent(workspace)}&version=${version}`;
}
export function eventUrl(id: string) {
  return `/api/v1/runs/${id}/events/stream?workspace_id=${encodeURIComponent(workspace)}`;
}
