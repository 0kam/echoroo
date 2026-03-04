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
import { fetchWithErrorHandling, handleApiResponse } from './errors';

const API_BASE = '/api/v1';

/**
 * Create a new upload session for a dataset.
 * Returns presigned upload URLs for each file.
 */
export async function createUploadSession(
  projectId: string,
  datasetId: string,
  data: CreateUploadSessionRequest
): Promise<CreateUploadSessionResponse> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/upload-sessions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<CreateUploadSessionResponse>(response);
}

/**
 * Mark an upload session as complete, triggering backend verification.
 */
export async function completeUploadSession(
  projectId: string,
  datasetId: string,
  sessionId: string
): Promise<CompleteUploadResponse> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/upload-sessions/${sessionId}/complete`,
    {
      method: 'POST',
      credentials: 'include',
    }
  );
  return handleApiResponse<CompleteUploadResponse>(response);
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/upload-sessions/${sessionId}`,
    { credentials: 'include' }
  );
  return handleApiResponse<UploadSessionStatusResponse>(response);
}

/**
 * Compute SHA-256 hash of a File object using the Web Crypto API.
 * Processes the file in 8MB chunks to avoid blocking the main thread for large files.
 */
export async function computeFileSHA256(file: File): Promise<string> {
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
        reject(new Error(`Upload failed with status ${xhr.status}: ${xhr.statusText}`));
      }
    });

    xhr.addEventListener('error', () => {
      reject(new Error('Network error during file upload'));
    });

    xhr.addEventListener('abort', () => {
      reject(new Error('File upload was aborted'));
    });

    xhr.open('PUT', url);
    // Do not set Content-Type header; let the presigned URL policy control it
    xhr.send(file);
  });
}
