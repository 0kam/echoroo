/**
 * Recorder API endpoints
 */

import type { Recorder, RecorderCreateRequest, RecorderUpdateRequest, RecorderListResponse } from '$lib/types';
import { apiClient } from './client';

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
