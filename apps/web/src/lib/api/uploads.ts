/**
 * Upload sessions API client for chunked, resumable browser uploads.
 */

import type {
  ActiveUploadSessionResponse,
  ChunkAcceptedResponse,
  CompleteUploadRequest,
  CompleteUploadResponse,
  CreateUploadSessionRequest,
  CreateUploadSessionResponse,
  UploadSessionStatusResponse,
} from '$lib/types/data';
import { apiClient } from './client';

const WEB_API_BASE = '/web-api/v1';
const CSRF_COOKIE_NAME = 'echoroo_csrf';

export function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const prefix = `${CSRF_COOKIE_NAME}=`;
  const parts = document.cookie ? document.cookie.split('; ') : [];
  for (const part of parts) {
    if (part.startsWith(prefix)) {
      try {
        return decodeURIComponent(part.slice(prefix.length));
      } catch {
        return part.slice(prefix.length);
      }
    }
  }
  return null;
}

function csrfHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getCsrfToken();
  if (token) headers['X-CSRF-Token'] = token;
  return headers;
}

export async function createUploadSession(
  projectId: string,
  datasetId: string,
  data: CreateUploadSessionRequest,
): Promise<CreateUploadSessionResponse> {
  return apiClient.post<CreateUploadSessionResponse>(
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/upload-sessions`,
    data,
    { headers: csrfHeaders() },
  );
}

export async function fetchActiveUploadSession(
  projectId: string,
  datasetId: string,
): Promise<ActiveUploadSessionResponse> {
  return apiClient.get<ActiveUploadSessionResponse>(
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/upload-sessions/active`,
  );
}

export async function completeUploadSession(
  projectId: string,
  datasetId: string,
  sessionId: string,
  body: CompleteUploadRequest = { skip_missing: false },
): Promise<CompleteUploadResponse> {
  return apiClient.post<CompleteUploadResponse>(
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/upload-sessions/${sessionId}/complete`,
    body,
    { headers: csrfHeaders() },
  );
}

export async function cancelUploadSession(
  projectId: string,
  datasetId: string,
  sessionId: string,
): Promise<void> {
  await apiClient.post<void>(
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/upload-sessions/${sessionId}/cancel`,
    undefined,
    { headers: csrfHeaders() },
  );
}

export async function fetchUploadSessionStatus(
  projectId: string,
  datasetId: string,
  sessionId: string,
): Promise<UploadSessionStatusResponse> {
  return apiClient.get<UploadSessionStatusResponse>(
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/upload-sessions/${sessionId}`,
  );
}

export const UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024;

export function chunkUrl(
  projectId: string,
  datasetId: string,
  sessionId: string,
  fileId: string,
  offset: number,
  restart = false,
): string {
  const url = `${WEB_API_BASE}/projects/${encodeURIComponent(projectId)}/datasets/${encodeURIComponent(datasetId)}/upload-sessions/${encodeURIComponent(sessionId)}/files/${encodeURIComponent(fileId)}/chunks?offset=${offset}`;
  return restart ? `${url}&restart=true` : url;
}

export async function sha256Hex(data: ArrayBuffer): Promise<string | null> {
  if (typeof crypto === 'undefined' || !crypto.subtle) return null;
  const digest = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export type ChunkResult =
  | { kind: 'ok'; received: number; complete: boolean }
  | { kind: 'offset'; received: number }
  | { kind: 'retry'; after: number }
  | { kind: 'unauthorized' }
  | { kind: 'fatal'; reason: 'session' | 'auth' | 'file'; message: string }
  | { kind: 'network' };

export interface PutChunkOptions {
  sha256: string | null;
  signal: AbortSignal;
  onProgress?: (loadedBytes: number) => void;
  /**
   * Abort the request when no upload progress and no response arrive for this
   * long. A connection that silently dies (NAT timeout, Wi-Fi drop without a
   * TCP reset, server paused) otherwise hangs the chunk forever; the scheduler
   * treats the abort as a network error and retries. 0 disables it.
   */
  inactivityMs?: number;
}

export const DEFAULT_CHUNK_INACTIVITY_MS = 30_000;

function parseResponseBody(responseText: string): unknown {
  if (!responseText) return null;
  try {
    return JSON.parse(responseText) as unknown;
  } catch {
    return responseText;
  }
}

function responseDetail(responseText: string): string {
  const body = parseResponseBody(responseText);
  if (typeof body === 'string') return body.slice(0, 200);
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail.slice(0, 200);
    if (detail && typeof detail === 'object' && 'detail' in detail) {
      const nested = (detail as { detail: unknown }).detail;
      if (typeof nested === 'string') return nested.slice(0, 200);
    }
  }
  return responseText.slice(0, 200);
}

export function putChunk(url: string, body: Blob, opts: PutChunkOptions): Promise<ChunkResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    let settled = false;

    const inactivityMs = opts.inactivityMs ?? DEFAULT_CHUNK_INACTIVITY_MS;
    let watchdog: ReturnType<typeof setTimeout> | null = null;
    let stalled = false;
    const armWatchdog = () => {
      if (inactivityMs <= 0) return;
      if (watchdog !== null) clearTimeout(watchdog);
      watchdog = setTimeout(() => {
        stalled = true;
        xhr.abort();
      }, inactivityMs);
    };

    const cleanup = () => {
      opts.signal.removeEventListener('abort', onSignalAbort);
      if (watchdog !== null) clearTimeout(watchdog);
    };

    const resolveOnce = (result: ChunkResult) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(result);
    };

    const rejectOnce = (error: unknown) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };

    const onSignalAbort = () => {
      if (settled) return;
      xhr.abort();
      rejectOnce(new DOMException('Aborted', 'AbortError'));
    };

    xhr.upload.addEventListener('progress', (event: ProgressEvent) => {
      armWatchdog();
      opts.onProgress?.(event.loaded);
    });
    xhr.addEventListener('load', () => {
      if (xhr.status === 200) {
        const bodyData = parseResponseBody(xhr.responseText ?? '');
        const accepted = bodyData as Partial<ChunkAcceptedResponse>;
        resolveOnce({
          kind: 'ok',
          received: typeof accepted.received_bytes === 'number' ? accepted.received_bytes : 0,
          complete: accepted.complete === true,
        });
      } else if (xhr.status === 409) {
        const bodyData = parseResponseBody(xhr.responseText ?? '');
        const detail =
          bodyData && typeof bodyData === 'object' && 'detail' in bodyData
            ? (bodyData as { detail: unknown }).detail
            : null;
        if (detail && typeof detail === 'object' && 'received_bytes' in detail) {
          const received = (detail as { received_bytes: unknown }).received_bytes;
          if (typeof received === 'number') {
            resolveOnce({ kind: 'offset', received });
            return;
          }
        }
        if (typeof detail === 'string') {
          resolveOnce({ kind: 'fatal', reason: 'session', message: detail.slice(0, 200) });
          return;
        }
        resolveOnce({ kind: 'fatal', reason: 'session', message: responseDetail(xhr.responseText ?? '') });
      } else if (xhr.status === 429) {
        const retryAfter = Number(xhr.getResponseHeader('Retry-After') ?? '');
        resolveOnce({ kind: 'retry', after: Number.isFinite(retryAfter) && retryAfter >= 0 ? retryAfter : 1 });
      } else if (xhr.status === 401) {
        resolveOnce({ kind: 'unauthorized' });
      } else if (xhr.status === 403 || xhr.status === 419) {
        resolveOnce({ kind: 'fatal', reason: 'auth', message: responseDetail(xhr.responseText ?? '') });
      } else if (xhr.status === 413 || xhr.status === 422) {
        resolveOnce({ kind: 'fatal', reason: 'file', message: responseDetail(xhr.responseText ?? '') });
      } else if (xhr.status >= 400) {
        resolveOnce({ kind: 'fatal', reason: 'file', message: responseDetail(xhr.responseText ?? '') });
      } else {
        resolveOnce({ kind: 'network' });
      }
    });
    xhr.addEventListener('error', () => resolveOnce({ kind: 'network' }));
    xhr.addEventListener('abort', () => {
      if (stalled) {
        // Our own watchdog fired: the connection went silent. Retry.
        resolveOnce({ kind: 'network' });
        return;
      }
      rejectOnce(new DOMException('Aborted', 'AbortError'));
    });

    xhr.open('PUT', url);
    xhr.withCredentials = true;
    const accessToken = apiClient.getAccessToken();
    if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
    const csrfToken = getCsrfToken();
    if (csrfToken) xhr.setRequestHeader('X-CSRF-Token', csrfToken);
    if (opts.sha256 !== null) xhr.setRequestHeader('X-Chunk-SHA256', opts.sha256);

    opts.signal.addEventListener('abort', onSignalAbort, { once: true });
    if (opts.signal.aborted) {
      onSignalAbort();
      return;
    }
    armWatchdog();
    xhr.send(body);
  });
}
