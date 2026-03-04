/**
 * Detection runs API client for TanStack Query.
 */

import type { DetectionRun, DetectionRunListResponse } from '$lib/types/detection';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

const API_BASE = '/api/v1';

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
 * Create a new detection run for a dataset.
 */
export async function createDetectionRun(
  projectId: string,
  datasetId: string
): Promise<DetectionRun> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/detection-runs`,
    {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset_id: datasetId,
        model_name: 'birdnet',
        model_version: '2.4',
      }),
    }
  );
  return handleApiResponse<DetectionRun>(response);
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
