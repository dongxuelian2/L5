export async function api<T>(path: string, body?: unknown, method = body === undefined ? "GET" : "POST", signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { method, headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error("Cannot reach the L5 service. Start npm run serve and try again.");
  }
  if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("Start the L5 Python service with npm run serve to use workspaces.");
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data as T;
}
export function message(error: unknown) { return error instanceof Error ? error.message : "Unable to complete this operation."; }
export function go(path: string) { window.location.hash = `#/${path}`; }
export function analysisPath(workspaceId: string, datasetId: string, signals: string[], range?: [number, number]) {
  const query = new URLSearchParams({ dataset: datasetId });
  signals.forEach(signal => query.append("signal", signal));
  if (range) { query.set("start", String(range[0])); query.set("end", String(range[1])); }
  return `workspaces/${workspaceId}/analysis?${query}`;
}
