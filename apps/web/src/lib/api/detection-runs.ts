/**
 * Detection runs API client for TanStack Query.
 */

import type { DetectionRun, DetectionRunListResponse } from '$lib/types/detection';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

const API_BASE = '/api/v1';

/** Map from model name to its default version string. */
const MODEL_VERSIONS: Record<string, string> = {
  birdnet: '2.4',
  perch: '2.0',
};

/**
 * Fetch detection runs for a project, optionally filtered by dataset server-side.
 */
export async function fetchDetectionRuns(
  projectId: string,
  datasetId?: string
): Promise<DetectionRunListResponse> {
  const url = new URL(`${API_BASE}/projects/${projectId}/detection-runs`, window.location.origin);
  if (datasetId) {
    url.searchParams.set('dataset_id', datasetId);
  }
  const response = await fetchWithErrorHandling(url.toString(), { credentials: 'include' });
  return handleApiResponse<DetectionRunListResponse>(response);
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/detection-runs`,
    {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset_id: datasetId,
        model_name: modelName,
        model_version: modelVersion,
        embedding_only: embeddingOnly,
      }),
    }
  );
  return handleApiResponse<DetectionRun>(response);
}

/**
 * Fetch the list of available ML model names from the server.
 */
export async function fetchAvailableModels(): Promise<string[]> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/detection-runs/available-models`,
    { credentials: 'include' }
  );
  const data = await handleApiResponse<{ models: string[] }>(response);
  return data.models;
}

/**
 * Retry a completed or failed detection run.
 */
export async function retryDetectionRun(
  projectId: string,
  runId: string
): Promise<DetectionRun> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/detection-runs/${runId}/retry`,
    { method: 'POST', credentials: 'include' }
  );
  return handleApiResponse<DetectionRun>(response);
}

/**
 * Cancel a pending or running detection run.
 */
export async function cancelDetectionRun(
  projectId: string,
  runId: string
): Promise<DetectionRun> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/detection-runs/${runId}/cancel`,
    { method: 'POST', credentials: 'include' }
  );
  return handleApiResponse<DetectionRun>(response);
}
