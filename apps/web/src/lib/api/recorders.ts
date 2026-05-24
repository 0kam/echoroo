/**
 * Recorder API endpoints.
 *
 * spec/009 PR 4: the public ``fetchRecorders`` call goes through
 * ``/web-api/v1`` (cookie + CSRF session boundary).
 *
 * spec/009 PR 5: the admin ``recorderApi`` surface (5 superuser-only
 * CRUD endpoints) now also lives on the BFF mount at
 * ``/web-api/v1/admin/recorders/*``. The legacy ``/api/v1/admin/*``
 * routes stay live for M2M API-key callers; cookie-session admins must
 * use the BFF or AuthRouterMiddleware 401s the request and the
 * frontend auto-logout triggers. Mutations attach ``X-CSRF-Token`` via
 * the inline ``csrfHeaders()`` helper used by every other migrated BFF
 * module.
 */

import type { Recorder, RecorderCreateRequest, RecorderUpdateRequest, RecorderListResponse } from '$lib/types';
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
 * Fetch all recorders (public, authenticated endpoint).
 */
export async function fetchRecorders(params?: { page?: number; limit?: number }): Promise<RecorderListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.page) searchParams.set('page', params.page.toString());
  if (params?.limit) searchParams.set('limit', params.limit.toString());
  const query = searchParams.toString();

  return apiClient.get<RecorderListResponse>(`${WEB_API_BASE}/recorders${query ? `?${query}` : ''}`);
}

export const recorderApi = {
  /**
   * List all recorders (superuser only)
   */
  list: async (params?: { page?: number; limit?: number }): Promise<RecorderListResponse> => {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.set('page', params.page.toString());
    if (params?.limit) queryParams.set('limit', params.limit.toString());
    const query = queryParams.toString();
    return apiClient.get<RecorderListResponse>(
      `${WEB_API_BASE}/admin/recorders${query ? `?${query}` : ''}`
    );
  },

  /**
   * Get a single recorder
   */
  get: async (id: string): Promise<Recorder> => {
    return apiClient.get<Recorder>(`${WEB_API_BASE}/admin/recorders/${id}`);
  },

  /**
   * Create a new recorder
   */
  create: async (data: RecorderCreateRequest): Promise<Recorder> => {
    return apiClient.post<Recorder>(
      `${WEB_API_BASE}/admin/recorders`,
      data,
      { headers: csrfHeaders() }
    );
  },

  /**
   * Update a recorder
   */
  update: async (id: string, data: RecorderUpdateRequest): Promise<Recorder> => {
    return apiClient.patch<Recorder>(
      `${WEB_API_BASE}/admin/recorders/${id}`,
      data,
      { headers: csrfHeaders() }
    );
  },

  /**
   * Delete a recorder
   */
  delete: async (id: string): Promise<void> => {
    return apiClient.delete<void>(
      `${WEB_API_BASE}/admin/recorders/${id}`,
      { headers: csrfHeaders() }
    );
  },
};
