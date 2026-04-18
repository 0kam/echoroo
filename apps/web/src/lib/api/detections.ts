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
import { apiClient } from './client';

const API_BASE = '/api/v1';

// ============================================
// Query param helpers
// ============================================

function buildDetectionParams(params?: DetectionFilters & { page?: number; page_size?: number; detection_run_id?: string }): string {
  if (!params) return '';
  const query = new URLSearchParams();
  if (params.tag_id !== undefined) query.set('tag_id', params.tag_id);
  if (params.status !== undefined) query.set('status', params.status);
  if (params.confidence_min !== undefined) query.set('confidence_min', String(params.confidence_min));
  if (params.confidence_max !== undefined) query.set('confidence_max', String(params.confidence_max));
  if (params.dataset_id !== undefined) query.set('dataset_id', params.dataset_id);
  if (params.recording_id !== undefined) query.set('recording_id', params.recording_id);
  if (params.detection_run_id !== undefined) query.set('detection_run_id', params.detection_run_id);
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
  params?: { dataset_id?: string; search?: string; locale?: string; detection_run_id?: string }
): Promise<SpeciesSummaryResponse> {
  const query = new URLSearchParams();
  if (params?.dataset_id) query.set('dataset_id', params.dataset_id);
  if (params?.search) query.set('search', params.search);
  if (params?.locale) query.set('locale', params.locale);
  if (params?.detection_run_id) query.set('detection_run_id', params.detection_run_id);
  const qs = query.toString() ? `?${query.toString()}` : '';
  return apiClient.get<SpeciesSummaryResponse>(
    `${API_BASE}/projects/${projectId}/detections/species-summary${qs}`
  );
}

// ============================================
// Detection list
// ============================================

/**
 * Fetch a paginated list of detections for a project with optional filters.
 */
export async function fetchDetections(
  projectId: string,
  params?: DetectionFilters & { page?: number; page_size?: number; detection_run_id?: string }
): Promise<DetectionListResponse> {
  const qs = buildDetectionParams(params);
  return apiClient.get<DetectionListResponse>(
    `${API_BASE}/projects/${projectId}/detections${qs}`
  );
}

// ============================================
// Detection actions
// ============================================

/**
 * Reassign a detection to a different species (tag).
 */
export async function changeDetectionSpecies(
  projectId: string,
  detectionId: string,
  data: ChangeSpeciesRequest
): Promise<Detection> {
  return apiClient.post<Detection>(
    `${API_BASE}/projects/${projectId}/detections/${detectionId}/change-species`,
    data
  );
}

/**
 * Create a new human detection manually.
 */
export async function createDetection(
  projectId: string,
  data: DetectionCreateRequest
): Promise<Detection> {
  return apiClient.post<Detection>(
    `${API_BASE}/projects/${projectId}/detections`,
    data
  );
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
  datasetId?: string,
  locale?: string,
  detectionRunId?: string
): Promise<DetectionTemporalDataResponse> {
  const params = new URLSearchParams();
  if (datasetId) params.set('dataset_id', datasetId);
  if (locale) params.set('locale', locale);
  if (detectionRunId) params.set('detection_run_id', detectionRunId);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<DetectionTemporalDataResponse>(
    `${API_BASE}/projects/${projectId}/detections/temporal-data${qs}`
  );
}

