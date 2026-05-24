/**
 * License API endpoints.
 *
 * spec/009 PR 5: the five superuser-only license CRUD endpoints now
 * resolve through the cookie + CSRF BFF mount
 * (`/web-api/v1/admin/licenses/*`). The legacy `/api/v1/admin/*`
 * routes stay live for M2M API-key callers; cookie-session admins must
 * use the BFF or AuthRouterMiddleware 401s the request and the
 * frontend auto-logout triggers. Mutations attach `X-CSRF-Token` via
 * the inline `csrfHeaders()` helper used by every other migrated BFF
 * module.
 */

import type { License, LicenseCreateRequest, LicenseUpdateRequest, LicenseListResponse } from '$lib/types';
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

export const licenseApi = {
  /**
   * List all licenses (superuser only)
   */
  list: async (): Promise<LicenseListResponse> => {
    return apiClient.get<LicenseListResponse>(`${WEB_API_BASE}/admin/licenses`);
  },

  /**
   * Get a single license
   */
  get: async (id: string): Promise<License> => {
    return apiClient.get<License>(`${WEB_API_BASE}/admin/licenses/${id}`);
  },

  /**
   * Create a new license
   */
  create: async (data: LicenseCreateRequest): Promise<License> => {
    return apiClient.post<License>(
      `${WEB_API_BASE}/admin/licenses`,
      data,
      { headers: csrfHeaders() }
    );
  },

  /**
   * Update a license
   */
  update: async (id: string, data: LicenseUpdateRequest): Promise<License> => {
    return apiClient.patch<License>(
      `${WEB_API_BASE}/admin/licenses/${id}`,
      data,
      { headers: csrfHeaders() }
    );
  },

  /**
   * Delete a license
   */
  delete: async (id: string): Promise<void> => {
    return apiClient.delete<void>(
      `${WEB_API_BASE}/admin/licenses/${id}`,
      { headers: csrfHeaders() }
    );
  },
};
