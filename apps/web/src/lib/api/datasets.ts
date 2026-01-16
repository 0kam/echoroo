/**
 * Datasets API client for TanStack Query.
 */

import type {
  Dataset,
  DatasetCreate,
  DatasetDetail,
  DatasetListParams,
  DatasetListResponse,
  DatasetStatistics,
  DatasetUpdate,
  DirectoryListResponse,
  ImportRequest,
  ImportStatusResponse,
} from '$lib/types/data';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

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
  const response = await fetchWithErrorHandling(url, { credentials: 'include' });
  return handleApiResponse<DatasetListResponse>(response);
}

/**
 * Fetch a single dataset by ID.
 */
export async function fetchDataset(
  projectId: string,
  datasetId: string
): Promise<DatasetDetail> {
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/datasets/${datasetId}`, {
    credentials: 'include',
  });
  return handleApiResponse<DatasetDetail>(response);
}

/**
 * Create a new dataset.
 */
export async function createDataset(
  projectId: string,
  data: DatasetCreate
): Promise<DatasetDetail> {
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/datasets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleApiResponse<DatasetDetail>(response);
}

/**
 * Update a dataset.
 */
export async function updateDataset(
  projectId: string,
  datasetId: string,
  data: DatasetUpdate
): Promise<DatasetDetail> {
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/datasets/${datasetId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleApiResponse<DatasetDetail>(response);
}

/**
 * Delete a dataset.
 */
export async function deleteDataset(projectId: string, datasetId: string): Promise<void> {
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/datasets/${datasetId}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    await handleApiResponse(response);
  }
}

/**
 * Start importing recordings from a dataset.
 */
export async function startImport(
  projectId: string,
  datasetId: string,
  data: ImportRequest = {}
): Promise<ImportStatusResponse> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/import`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<ImportStatusResponse>(response);
}

/**
 * Rescan a dataset for new files.
 */
export async function rescanDataset(
  projectId: string,
  datasetId: string
): Promise<ImportStatusResponse> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/rescan`,
    {
      method: 'POST',
      credentials: 'include',
    }
  );
  return handleApiResponse<ImportStatusResponse>(response);
}

/**
 * Get import status for a dataset.
 */
export async function fetchImportStatus(
  projectId: string,
  datasetId: string
): Promise<ImportStatusResponse> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/import-status`,
    { credentials: 'include' }
  );
  return handleApiResponse<ImportStatusResponse>(response);
}

/**
 * Get statistics for a dataset.
 */
export async function fetchDatasetStatistics(
  projectId: string,
  datasetId: string
): Promise<DatasetStatistics> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/datasets/${datasetId}/statistics`,
    { credentials: 'include' }
  );
  return handleApiResponse<DatasetStatistics>(response);
}

/**
 * List directories available for dataset creation.
 */
export async function fetchDirectories(path?: string): Promise<DirectoryListResponse> {
  const searchParams = path ? new URLSearchParams({ path }) : '';
  const url = `${API_BASE}/datasets/directories${searchParams ? '?' + searchParams : ''}`;

  const response = await fetchWithErrorHandling(url, { credentials: 'include' });
  return handleApiResponse<DirectoryListResponse>(response);
}
