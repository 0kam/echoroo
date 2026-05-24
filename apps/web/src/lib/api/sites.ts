/**
 * Sites API client for TanStack Query.
 *
 * spec/009 PR 3a: all site CRUD calls go through ``/web-api/v1`` (cookie
 * + CSRF session boundary). Mutations attach ``X-CSRF-Token`` via the
 * inline helper below.
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
 * Fetch sites for a project.
 */
export async function fetchSites(
  projectId: string,
  params: SiteListParams = {}
): Promise<SiteListResponse> {
  const searchParams = new URLSearchParams();
  if (params.page) searchParams.set('page', params.page.toString());
  if (params.page_size) searchParams.set('page_size', params.page_size.toString());

  const url = `${WEB_API_BASE}/projects/${projectId}/sites?${searchParams}`;
  return apiClient.get<SiteListResponse>(url);
}

/**
 * Fetch a single site by ID.
 */
export async function fetchSite(projectId: string, siteId: string): Promise<SiteDetail> {
  return apiClient.get<SiteDetail>(`${WEB_API_BASE}/projects/${projectId}/sites/${siteId}`);
}

/**
 * Create a new site.
 */
export async function createSite(projectId: string, data: SiteCreate): Promise<Site> {
  return apiClient.post<Site>(
    `${WEB_API_BASE}/projects/${projectId}/sites`,
    data,
    { headers: csrfHeaders() }
  );
}

/**
 * Update a site.
 */
export async function updateSite(
  projectId: string,
  siteId: string,
  data: SiteUpdate
): Promise<Site> {
  return apiClient.patch<Site>(
    `${WEB_API_BASE}/projects/${projectId}/sites/${siteId}`,
    data,
    { headers: csrfHeaders() }
  );
}

/**
 * Delete a site.
 */
export async function deleteSite(projectId: string, siteId: string): Promise<void> {
  return apiClient.delete<void>(
    `${WEB_API_BASE}/projects/${projectId}/sites/${siteId}`,
    { headers: csrfHeaders() }
  );
}
