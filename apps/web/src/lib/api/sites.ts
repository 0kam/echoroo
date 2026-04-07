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
import { apiClient } from './client';

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
  return apiClient.get<SiteListResponse>(url);
}

/**
 * Fetch a single site by ID.
 */
export async function fetchSite(projectId: string, siteId: string): Promise<SiteDetail> {
  return apiClient.get<SiteDetail>(`${API_BASE}/projects/${projectId}/sites/${siteId}`);
}

/**
 * Create a new site.
 */
export async function createSite(projectId: string, data: SiteCreate): Promise<Site> {
  return apiClient.post<Site>(`${API_BASE}/projects/${projectId}/sites`, data);
}

/**
 * Update a site.
 */
export async function updateSite(
  projectId: string,
  siteId: string,
  data: SiteUpdate
): Promise<Site> {
  return apiClient.patch<Site>(`${API_BASE}/projects/${projectId}/sites/${siteId}`, data);
}

/**
 * Delete a site.
 */
export async function deleteSite(projectId: string, siteId: string): Promise<void> {
  return apiClient.delete<void>(`${API_BASE}/projects/${projectId}/sites/${siteId}`);
}
