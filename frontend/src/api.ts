// Keep frontend data access behind the versioned backend API.
export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, options);
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Request failed.');
  return body;
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return request(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
}

export function query(values: Record<string, string | number | undefined>): string {
  return new URLSearchParams(Object.entries(values).filter(([, value]) => value !== undefined).map(([key, value]) => [key, String(value)])).toString();
}

export type Repository = {id: string; name: string; source: string; commit_sha: string};
export type Snapshot = {id: string; status: string; commit_sha: string; metrics: {files: number; chunks?: number; total_seconds?: number; skipped: {path: string; reason: string}[]}};
export type Task = {id: string; repository_id: string; status: string; progress: number; error: string | null};
export type Hit = {id: string; path: string; start_line: number; end_line: number; excerpt: string; symbol: string | null; symbol_id: string | null; score: number; origins: string[]};
export type Symbol = {id: string; name: string; qualified_name: string; kind: string; signature: string; start_line: number; end_line: number; path: string};
export type Reference = {path: string; start_line: number; column: number; name: string; status: string};
export type GraphNode = {id: string; label: string; path: string | null; symbol_id: string | null; external: boolean};
export type GraphData = {nodes: GraphNode[]; edges: {source: string; target: string; kind: string; status: string}[]; truncated: boolean};
