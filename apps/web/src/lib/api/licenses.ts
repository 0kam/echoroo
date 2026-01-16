/**
 * License API endpoints
 */

import type { License, LicenseCreateRequest, LicenseUpdateRequest, LicenseListResponse } from '$lib/types';
import { apiClient } from './client';

export const licenseApi = {
  /**
   * List all licenses (superuser only)
   */
  list: async (): Promise<LicenseListResponse> => {
    return apiClient.get<LicenseListResponse>('/api/v1/admin/licenses');
  },

  /**
   * Get a single license
   */
  get: async (id: string): Promise<License> => {
    return apiClient.get<License>(`/api/v1/admin/licenses/${id}`);
  },

  /**
   * Create a new license
   */
  create: async (data: LicenseCreateRequest): Promise<License> => {
    return apiClient.post<License>('/api/v1/admin/licenses', data);
  },

  /**
   * Update a license
   */
  update: async (id: string, data: LicenseUpdateRequest): Promise<License> => {
    return apiClient.patch<License>(`/api/v1/admin/licenses/${id}`, data);
  },

  /**
   * Delete a license
   */
  delete: async (id: string): Promise<void> => {
    return apiClient.delete<void>(`/api/v1/admin/licenses/${id}`);
  },
};
