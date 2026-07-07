/**
 * Detection runs API client for TanStack Query.
 *
 * spec/009 PR 2: all mutations route through the first-party BFF surface
 * (`/web-api/v1/*`) so they pass through the cookie + CSRF middleware
 * stack. The legacy `/api/v1` route is now reserved for programmatic
 * API-key callers (FR-006).
 */

import type { DetectionRun, DetectionRunListResponse, DetectionRunType } from '$lib/types/detection';
import { apiClient } from './client';

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

/** Map from model name to its default version string. */
const MODEL_VERSIONS: Record<string, string> = {
  birdnet: '2.4',
  perch: '2.0',
};

/**
 * Fetch detection runs for a project, optionally filtered by dataset and/or
 * run type server-side. When `runType` is provided the returned totals/pages
 * are scoped to that type, so callers can rely on server-side filtering rather
 * than a client-side heuristic.
 */
export async function fetchDetectionRuns(
  projectId: string,
  datasetId?: string,
  runType?: DetectionRunType
): Promise<DetectionRunListResponse> {
  const url = new URL(`${WEB_API_BASE}/projects/${projectId}/detection-runs`, window.location.origin);
  if (datasetId) {
    url.searchParams.set('dataset_id', datasetId);
  }
  if (runType) {
    url.searchParams.set('run_type', runType);
  }
  return apiClient.get<DetectionRunListResponse>(url.pathname + url.search);
}

/**
 * Create a new detection run for a dataset using the specified model.
 * @param modelName - Model identifier, e.g. "birdnet" or "perch"
 * @param embeddingOnly - When true, only generate embeddings without species detection
 */
export async function createDetectionRun(
  projectId: string,
  datasetId: string,
  modelName: string = 'birdnet',
  embeddingOnly: boolean = false
): Promise<DetectionRun> {
  const modelVersion = MODEL_VERSIONS[modelName] ?? '1.0';
  return apiClient.post<DetectionRun>(
    `${WEB_API_BASE}/projects/${projectId}/detection-runs`,
    {
      dataset_id: datasetId,
      model_name: modelName,
      model_version: modelVersion,
      embedding_only: embeddingOnly,
    },
    { headers: csrfHeaders() }
  );
}

/**
 * Fetch the list of available ML model names from the server.
 */
export async function fetchAvailableModels(): Promise<string[]> {
  const data = await apiClient.get<{ models: string[] }>(
    `${WEB_API_BASE}/detection-runs/available-models`
  );
  return data.models;
}

/**
 * Retry a completed or failed detection run.
 */
export async function retryDetectionRun(
  projectId: string,
  runId: string
): Promise<DetectionRun> {
  return apiClient.post<DetectionRun>(
    `${WEB_API_BASE}/projects/${projectId}/detection-runs/${runId}/retry`,
    undefined,
    { headers: csrfHeaders() }
  );
}

/**
 * Cancel a pending or running detection run.
 */
export async function cancelDetectionRun(
  projectId: string,
  runId: string
): Promise<DetectionRun> {
  return apiClient.post<DetectionRun>(
    `${WEB_API_BASE}/projects/${projectId}/detection-runs/${runId}/cancel`,
    undefined,
    { headers: csrfHeaders() }
  );
}
