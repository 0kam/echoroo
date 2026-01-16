/**
 * Recordings API endpoints
 */

import type { Recording, PaginatedResponse } from '$lib/types';
import { apiClient } from './client';

export const recordingsApi = {
  /**
   * List all recordings with pagination
   */
  list: async (params?: {
    page?: number;
    page_size?: number;
  }): Promise<PaginatedResponse<Recording>> => {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.set('page', params.page.toString());
    if (params?.page_size) queryParams.set('page_size', params.page_size.toString());

    const query = queryParams.toString();
    const endpoint = `/api/v1/recordings${query ? `?${query}` : ''}`;

    return apiClient.get<PaginatedResponse<Recording>>(endpoint);
  },

  /**
   * Get a single recording by ID
   */
  get: async (id: string): Promise<Recording> => {
    return apiClient.get<Recording>(`/api/v1/recordings/${id}`);
  },

  /**
   * Create a new recording
   */
  create: async (data: Partial<Recording>): Promise<Recording> => {
    return apiClient.post<Recording>('/api/v1/recordings', data);
  },

  /**
   * Update a recording
   */
  update: async (id: string, data: Partial<Recording>): Promise<Recording> => {
    return apiClient.patch<Recording>(`/api/v1/recordings/${id}`, data);
  },

  /**
   * Delete a recording
   */
  delete: async (id: string): Promise<void> => {
    return apiClient.delete<void>(`/api/v1/recordings/${id}`);
  },
};
