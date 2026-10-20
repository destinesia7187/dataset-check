import type { ApiErrorPayload, Run } from './types';

const base = '/api/v1';
export class ApiError extends Error {
  constructor(public status: number, public payload: ApiErrorPayload) { super(payload.message); this.name = 'ApiError'; }
}
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.method && !['GET', 'HEAD'].includes(init.method)) headers.set('X-Dataset-Check', '1');
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(path.startsWith('/api/') ? path : base + path, { ...init, headers });
  if (!response.ok) {
    let payload: ApiErrorPayload;
    try { const data = await response.json(); payload = data.error ?? { code: 'HTTP_ERROR', message: `Server error (${response.status})`, details: data }; }
    catch { payload = { code: 'HTTP_ERROR', message: `The server returned error ${response.status}`, details: null }; }
    throw new ApiError(response.status, payload);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export async function download(runId: string, format: string, filename: string): Promise<void> {
  // Validate availability using the small status resource; leave file streaming
  // to the browser download manager rather than retaining a whole report Blob.
  const run = await request<Run>(`/runs/${runId}`);
  if (run.status !== 'succeeded') {
    throw new ApiError(409, { code: 'RUN_NOT_READY', message: 'Exports are available after the check completes successfully.', details: null });
  }
  const anchor = document.createElement('a');
  anchor.href = `${base}/runs/${runId}/exports/${format}`;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.payload.message;
  return 'The connection to the server was lost. The operation may have been accepted. Retry using the saved request key.';
}
export function pendingRead<T>(key: string): T | null { try { return JSON.parse(localStorage.getItem(key) ?? 'null') as T | null; } catch { return null; } }
export function pendingWrite(key: string, value: unknown): void { try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value)); } catch { /* Browser storage may be disabled; in-memory state still retries safely. */ } }
