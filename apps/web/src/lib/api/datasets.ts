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

  const url = `${WEB_API_BASE}/projects/${projectId}/datasets?${searchParams}`;
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
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}`
  );
}

/**
 * Create a new dataset.
 */
export async function createDataset(
  projectId: string,
  data: DatasetCreate
): Promise<DatasetDetail> {
  return apiClient.post<DatasetDetail>(`${WEB_API_BASE}/projects/${projectId}/datasets`, data, {
    headers: csrfHeaders(),
  });
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
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}`,
    data,
    { headers: csrfHeaders() }
  );
}

/**
 * Delete a dataset.
 */
export async function deleteDataset(projectId: string, datasetId: string): Promise<void> {
  return apiClient.delete<void>(
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}`,
    { headers: csrfHeaders() }
  );
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
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/import`,
    data,
    { headers: csrfHeaders() }
  );
}

/**
 * Rescan a dataset for new files.
 *
 * NOTE: the backend route `/datasets/{id}/rescan` is not yet implemented;
 * the path migrated to `/web-api/v1` as part of spec/009 PR 2 so when the
 * backend handler lands it will already live on the first-party surface.
 * Until then the call returns HTTP 404 (same as before the migration).
 */
export async function rescanDataset(
  projectId: string,
  datasetId: string
): Promise<ImportStatusResponse> {
  return apiClient.post<ImportStatusResponse>(
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/rescan`,
    undefined,
    { headers: csrfHeaders() }
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
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/import-status`
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
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/statistics`
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
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/datetime-config`
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
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/datetime-config/auto-detect`,
    undefined,
    { headers: csrfHeaders() }
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
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/datetime-config/test`,
    { pattern, format_str: formatStr, timezone: timezone || null },
    { headers: csrfHeaders() }
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
    `${WEB_API_BASE}/projects/${projectId}/datasets/${datasetId}/datetime-config/apply`,
    { pattern, format_str: formatStr, timezone: timezone || null },
    { headers: csrfHeaders() }
  );
}
