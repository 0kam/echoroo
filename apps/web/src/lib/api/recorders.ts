/**
 * Recorder API endpoints.
 *
 * spec/009 PR 4: the public ``fetchRecorders`` call goes through
 * ``/web-api/v1`` (cookie + CSRF session boundary). The admin
 * ``recorderApi`` surface stays on the legacy ``/api/v1/admin/recorders``
 * mount — those routes are superuser-only and not part of the BFF
 * migration scope.
 */

import type { Recorder, RecorderCreateRequest, RecorderUpdateRequest, RecorderListResponse } from '$lib/types';
import { apiClient } from './client';

const WEB_API_BASE = '/web-api/v1';

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
    return apiClient.get<RecorderListResponse>(`/api/v1/admin/recorders${query ? `?${query}` : ''}`);
  },

  /**
   * Get a single recorder
   */
  get: async (id: string): Promise<Recorder> => {
    return apiClient.get<Recorder>(`/api/v1/admin/recorders/${id}`);
  },

  /**
   * Create a new recorder
   */
  create: async (data: RecorderCreateRequest): Promise<Recorder> => {
    return apiClient.post<Recorder>('/api/v1/admin/recorders', data);
  },

  /**
   * Update a recorder
   */
  update: async (id: string, data: RecorderUpdateRequest): Promise<Recorder> => {
    return apiClient.patch<Recorder>(`/api/v1/admin/recorders/${id}`, data);
  },

  /**
   * Delete a recorder
   */
  delete: async (id: string): Promise<void> => {
    return apiClient.delete<void>(`/api/v1/admin/recorders/${id}`);
  },
};
