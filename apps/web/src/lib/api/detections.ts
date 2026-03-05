/**
 * Detections API client for the Detection Review feature.
 */

import type {
  Detection,
  DetectionCreateRequest,
  DetectionListResponse,
  SpeciesSummaryResponse,
  ChangeSpeciesRequest,
  DetectionFilters,
  DetectionTemporalDataResponse,
} from '$lib/types/detection';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

const API_BASE = '/api/v1';

// ============================================
// Query param helpers
// ============================================

function buildDetectionParams(params?: DetectionFilters & { page?: number; page_size?: number }): string {
  if (!params) return '';
  const query = new URLSearchParams();
  if (params.tag_id !== undefined) query.set('tag_id', params.tag_id);
  if (params.status !== undefined) query.set('status', params.status);
  if (params.confidence_min !== undefined) query.set('confidence_min', String(params.confidence_min));
  if (params.confidence_max !== undefined) query.set('confidence_max', String(params.confidence_max));
  if (params.dataset_id !== undefined) query.set('dataset_id', params.dataset_id);
  if (params.recording_id !== undefined) query.set('recording_id', params.recording_id);
  if (params.page !== undefined) query.set('page', String(params.page));
  if (params.page_size !== undefined) query.set('page_size', String(params.page_size));
  const str = query.toString();
  return str ? `?${str}` : '';
}

// ============================================
// Species summary
// ============================================

/**
 * Fetch aggregated species detection statistics for a project.
 */
export async function fetchSpeciesSummary(
  projectId: string,
  params?: { dataset_id?: string; search?: string }
): Promise<SpeciesSummaryResponse> {
  const query = new URLSearchParams();
  if (params?.dataset_id) query.set('dataset_id', params.dataset_id);
  if (params?.search) query.set('search', params.search);
  const qs = query.toString() ? `?${query.toString()}` : '';
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/detections/species-summary${qs}`,
    { credentials: 'include' }
  );
  return handleApiResponse<SpeciesSummaryResponse>(response);
}

// ============================================
// Detection list
// ============================================

/**
 * Fetch a paginated list of detections for a project with optional filters.
 */
export async function fetchDetections(
  projectId: string,
  params?: DetectionFilters & { page?: number; page_size?: number }
): Promise<DetectionListResponse> {
  const qs = buildDetectionParams(params);
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/detections${qs}`,
    { credentials: 'include' }
  );
  return handleApiResponse<DetectionListResponse>(response);
}

// ============================================
// Detection actions
// ============================================

/**
 * Confirm (accept) a detection as a valid occurrence.
 *
 * When `timeRange` is provided, the confirmed detection's start/end times
 * are updated to match.  When omitted the backend preserves the original
 * times (quick-confirm).
 */
export async function confirmDetection(
  projectId: string,
  detectionId: string,
  timeRange?: { start_time: number; end_time: number }
): Promise<Detection> {
  const options: RequestInit = {
    method: 'POST',
    credentials: 'include',
  };
  if (timeRange) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(timeRange);
  }
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/detections/${detectionId}/confirm`,
    options
  );
  return handleApiResponse<Detection>(response);
}

/**
 * Reject a detection as a false positive or incorrect identification.
 */
export async function rejectDetection(
  projectId: string,
  detectionId: string
): Promise<Detection> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/detections/${detectionId}/reject`,
    {
      method: 'POST',
      credentials: 'include',
    }
  );
  return handleApiResponse<Detection>(response);
}

/**
 * Reassign a detection to a different species (tag).
 */
export async function changeDetectionSpecies(
  projectId: string,
  detectionId: string,
  data: ChangeSpeciesRequest
): Promise<Detection> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/detections/${detectionId}/change-species`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<Detection>(response);
}

/**
 * Create a new human detection manually.
 */
export async function createDetection(
  projectId: string,
  data: DetectionCreateRequest
): Promise<Detection> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/detections`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<Detection>(response);
}

// ============================================
// Temporal data
// ============================================

/**
 * Fetch hourly detection activity data for all species in a project.
 * Used to render PolarHeatmap visualizations.
 */
export async function fetchTemporalData(
  projectId: string,
  datasetId?: string
): Promise<DetectionTemporalDataResponse> {
  const params = new URLSearchParams();
  if (datasetId) params.set('dataset_id', datasetId);
  const qs = params.toString() ? `?${params.toString()}` : '';
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/detections/temporal-data${qs}`,
    { credentials: 'include' }
  );
  return handleApiResponse<DetectionTemporalDataResponse>(response);
}

/**
 * Delete a detection permanently.
 */
export async function deleteDetection(
  projectId: string,
  detectionId: string
): Promise<void> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/detections/${detectionId}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );
  if (response.ok) {
    return;
  }
  await handleApiResponse(response);
}
