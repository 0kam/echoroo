/**
 * Upload sessions API client for TanStack Query.
 * Handles file upload sessions, presigned URL uploads, and status polling.
 */

import type {
  CompleteUploadResponse,
  CreateUploadSessionRequest,
  CreateUploadSessionResponse,
  UploadSessionStatusResponse,
} from '$lib/types/data';
import { apiClient } from './client';

// spec/009 PR 3a: upload-session orchestration (create / complete /
// status) migrated to ``/web-api/v1``. The S3 PUT itself
// (``uploadFileToPresignedUrl`` below) talks to S3 directly and never
// flows through the FastAPI app, so it is intentionally out of scope.
const WEB_API_BASE = '/web-api/v1';
const CSRF_COOKIE_NAME = 'echoroo_csrf';

function getCsrfToken(): string | null {
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

/**
 * Create a new upload session for a dataset.
 * Returns presigned upload URLs for each file.
 */
export async function createUploadSession(
  projectId: string,
  datasetId: string,
  data: CreateUploadSessionRequest
): Promise<CreateUploadSessionResponse> {
  return apiClient.post<CreateUploadSessionResponse>(
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/upload-sessions`,
    data,
    { headers: csrfHeaders() }
  );
}

/**
 * Mark an upload session as complete, triggering backend verification.
 */
export async function completeUploadSession(
  projectId: string,
  datasetId: string,
  sessionId: string
): Promise<CompleteUploadResponse> {
  return apiClient.post<CompleteUploadResponse>(
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/upload-sessions/${sessionId}/complete`,
    undefined,
    { headers: csrfHeaders() }
  );
}

/**
 * Fetch the current status of an upload session.
 * Used for polling during validating/importing phases.
 */
export async function fetchUploadSessionStatus(
  projectId: string,
  datasetId: string,
  sessionId: string
): Promise<UploadSessionStatusResponse> {
  return apiClient.get<UploadSessionStatusResponse>(
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/upload-sessions/${sessionId}`
  );
}

/**
 * Compute SHA-256 hash of a File object using the Web Crypto API.
 * Processes the file in 8MB chunks to avoid blocking the main thread for large files.
 * Returns null if crypto.subtle is unavailable (e.g. HTTP non-secure contexts).
 */
export async function computeFileSHA256(file: File): Promise<string | null> {
  // crypto.subtle is only available in secure contexts (HTTPS or localhost)
  if (!crypto.subtle) {
    return null;
  }

  const CHUNK_SIZE = 8 * 1024 * 1024; // 8 MB chunks
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

  // For single-chunk files, use a direct approach
  if (totalChunks <= 1) {
    const buffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    return bufferToHex(hashBuffer);
  }

  // For multi-chunk files, concatenate all chunks then hash
  // (Web Crypto API doesn't support streaming SHA-256 natively)
  const buffer = await file.arrayBuffer();
  const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
  return bufferToHex(hashBuffer);
}

/**
 * Convert an ArrayBuffer to a hex string.
 */
function bufferToHex(buffer: ArrayBuffer): string {
  const byteArray = new Uint8Array(buffer);
  return Array.from(byteArray)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Convert a presigned URL to a same-origin relative path.
 *
 * The backend generates presigned URLs with an absolute origin
 * (e.g. http://localhost:3000/s3-proxy/echoroo/...) based on
 * S3_PUBLIC_ENDPOINT_URL.  When the user accesses the app through
 * SSH port-forwarding or a different host/IP, the origin in the
 * presigned URL may not match the browser's actual origin, causing
 * a cross-origin request that fails due to CORS.
 *
 * By stripping the origin and keeping only the path + query, the
 * browser always sends a same-origin request through the Vite
 * dev proxy (or production reverse proxy), avoiding CORS entirely.
 */
function toRelativeUrl(absoluteUrl: string): string {
  try {
    const parsed = new URL(absoluteUrl);
    return parsed.pathname + parsed.search;
  } catch {
    // If it's already relative or unparseable, return as-is
    return absoluteUrl;
  }
}

/**
 * Upload a file to a presigned URL via HTTP PUT.
 * Uses XMLHttpRequest to support upload progress tracking.
 *
 * @param url - Presigned URL from the upload session
 * @param file - File object to upload
 * @param onProgress - Optional callback receiving upload percentage (0-100)
 */
export function uploadFileToPresignedUrl(
  url: string,
  file: File,
  onProgress?: (percent: number) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && onProgress) {
        const percent = Math.round((event.loaded / event.total) * 100);
        onProgress(percent);
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(100);
        resolve();
      } else {
        const body = xhr.responseText?.substring(0, 200) || '';
        reject(new Error(`Upload failed with status ${xhr.status}: ${xhr.statusText}. ${body}`));
      }
    });

    xhr.addEventListener('error', () => {
      // XHR error events fire for network-level failures (CORS, DNS, connection refused, etc.)
      // Include any available response info to help debugging.
      const detail = xhr.statusText || 'no details available';
      reject(new Error(`Network error during file upload (${detail}). Check browser console for CORS or connectivity issues.`));
    });

    xhr.addEventListener('abort', () => {
      reject(new Error('File upload was aborted'));
    });

    // Convert absolute presigned URL to relative path to ensure same-origin
    // requests regardless of how the user accesses the app (SSH tunnel, IP, etc.)
    const relativeUrl = toRelativeUrl(url);
    xhr.open('PUT', relativeUrl);
    // Do not set Content-Type header; let the presigned URL policy control it
    xhr.send(file);
  });
}
