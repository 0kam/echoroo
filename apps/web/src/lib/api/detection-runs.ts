/**
 * Detection runs API client for TanStack Query.
 */

import type { DetectionRun, DetectionRunListResponse } from '$lib/types/detection';
import { apiClient } from './client';

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
    `${API_BASE}/projects/${projectId}/detection-runs`,
    {
      dataset_id: datasetId,
      model_name: modelName,
      model_version: modelVersion,
      embedding_only: embeddingOnly,
    }
  );
}

/**
 * Fetch the list of available ML model names from the server.
 */
export async function fetchAvailableModels(): Promise<string[]> {
  const data = await apiClient.get<{ models: string[] }>(
    `${API_BASE}/detection-runs/available-models`
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
    `${API_BASE}/projects/${projectId}/detection-runs/${runId}/retry`
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
    `${API_BASE}/projects/${projectId}/detection-runs/${runId}/cancel`
  );
}
