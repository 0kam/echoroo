/**
 * Sites API client for TanStack Query.
 */

import type {
  Site,
  SiteCreate,
  SiteDetail,
  SiteListParams,
  SiteListResponse,
  SiteUpdate,
} from '$lib/types/data';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

const API_BASE = '/api/v1';

/**
 * Fetch sites for a project.
 */
export async function fetchSites(
  projectId: string,
  params: SiteListParams = {}
): Promise<SiteListResponse> {
  const searchParams = new URLSearchParams();
  if (params.page) searchParams.set('page', params.page.toString());
  if (params.page_size) searchParams.set('page_size', params.page_size.toString());

  const url = `${API_BASE}/projects/${projectId}/sites?${searchParams}`;
  const response = await fetchWithErrorHandling(url, { credentials: 'include' });
  return handleApiResponse<SiteListResponse>(response);
}

/**
 * Fetch a single site by ID.
 */
export async function fetchSite(projectId: string, siteId: string): Promise<SiteDetail> {
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/sites/${siteId}`, {
    credentials: 'include',
  });
  return handleApiResponse<SiteDetail>(response);
}

/**
 * Create a new site.
 */
export async function createSite(projectId: string, data: SiteCreate): Promise<Site> {
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/sites`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleApiResponse<Site>(response);
}

/**
 * Update a site.
 */
export async function updateSite(
  projectId: string,
  siteId: string,
  data: SiteUpdate
): Promise<Site> {
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/sites/${siteId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleApiResponse<Site>(response);
}

/**
 * Delete a site.
 */
export async function deleteSite(projectId: string, siteId: string): Promise<void> {
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/sites/${siteId}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    await handleApiResponse(response);
  }
}
