/**
 * Datasets API client for TanStack Query.
 */

import type {
  DatasetCreate,
  DatasetDetail,
  DatasetListParams,
  DatasetListResponse,
  DatasetStatistics,
  DatasetUpdate,
  DatetimeApplyResult,
  DatetimeAutoDetectResult,
  DatetimeConfig,
  DatetimeTestResult,
  ImportRequest,
  ImportStatusResponse,
} from '$lib/types/data';
import { apiClient } from './client';

const API_BASE = '/api/v1';

/**
 * Fetch datasets for a project.
 */
export async function fetchDatasets(
  projectId: string,
  params: DatasetListParams = {}
): Promise<DatasetListResponse> {
  const searchParams = new URLSearchParams();
  if (params.page) searchParams.set('page', params.page.toString());
  if (params.page_size) searchParams.set('page_size', params.page_size.toString());
  if (params.site_id) searchParams.set('site_id', params.site_id);
  if (params.status) searchParams.set('status', params.status);
  if (params.visibility) searchParams.set('visibility', params.visibility);
  if (params.search) searchParams.set('search', params.search);

  const url = `${API_BASE}/projects/${projectId}/datasets?${searchParams}`;
  return apiClient.get<DatasetListResponse>(url);
}

/**
 * Fetch a single dataset by ID.
 */
export async function fetchDataset(
  projectId: string,
  datasetId: string
): Promise<DatasetDetail> {
  return apiClient.get<DatasetDetail>(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}`
  );
}

/**
 * Create a new dataset.
 */
export async function createDataset(
  projectId: string,
  data: DatasetCreate
): Promise<DatasetDetail> {
  return apiClient.post<DatasetDetail>(`${API_BASE}/projects/${projectId}/datasets`, data);
}

/**
 * Update a dataset.
 */
export async function updateDataset(
  projectId: string,
  datasetId: string,
  data: DatasetUpdate
): Promise<DatasetDetail> {
  return apiClient.patch<DatasetDetail>(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}`,
    data
  );
}

/**
 * Delete a dataset.
 */
export async function deleteDataset(projectId: string, datasetId: string): Promise<void> {
  return apiClient.delete<void>(`${API_BASE}/projects/${projectId}/datasets/${datasetId}`);
}

/**
 * Start importing recordings from a dataset.
 */
export async function startImport(
  projectId: string,
  datasetId: string,
  data: ImportRequest = {}
): Promise<ImportStatusResponse> {
  return apiClient.post<ImportStatusResponse>(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/import`,
    data
  );
}

/**
 * Rescan a dataset for new files.
 */
export async function rescanDataset(
  projectId: string,
  datasetId: string
): Promise<ImportStatusResponse> {
  return apiClient.post<ImportStatusResponse>(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/rescan`
  );
}

/**
 * Get import status for a dataset.
 */
export async function fetchImportStatus(
  projectId: string,
  datasetId: string
): Promise<ImportStatusResponse> {
  return apiClient.get<ImportStatusResponse>(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/import-status`
  );
}

/**
 * Get statistics for a dataset.
 */
export async function fetchDatasetStatistics(
  projectId: string,
  datasetId: string
): Promise<DatasetStatistics> {
  return apiClient.get<DatasetStatistics>(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/statistics`
  );
}

/**
 * Get datetime parsing configuration for a dataset.
 */
export async function fetchDatetimeConfig(
  projectId: string,
  datasetId: string
): Promise<DatetimeConfig> {
  return apiClient.get<DatetimeConfig>(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/datetime-config`
  );
}

/**
 * Auto-detect datetime pattern from sample filenames.
 */
export async function autoDetectDatetime(
  projectId: string,
  datasetId: string
): Promise<DatetimeAutoDetectResult> {
  return apiClient.post<DatetimeAutoDetectResult>(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/datetime-config/auto-detect`
  );
}

/**
 * Test a datetime pattern against sample filenames.
 */
export async function testDatetimePattern(
  projectId: string,
  datasetId: string,
  pattern: string,
  formatStr: string,
  timezone?: string
): Promise<DatetimeTestResult[]> {
  return apiClient.post<DatetimeTestResult[]>(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/datetime-config/test`,
    { pattern, format_str: formatStr, timezone: timezone || null }
  );
}

/**
 * Apply a datetime pattern to all recordings in a dataset.
 */
export async function applyDatetimePattern(
  projectId: string,
  datasetId: string,
  pattern: string,
  formatStr: string,
  timezone?: string
): Promise<DatetimeApplyResult> {
  return apiClient.post<DatetimeApplyResult>(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/datetime-config/apply`,
    { pattern, format_str: formatStr, timezone: timezone || null }
  );
}
