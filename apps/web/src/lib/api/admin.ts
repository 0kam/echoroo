/**
 * Admin API endpoints
 */

import type {
  User,
  AdminUserListResponse,
  SystemSetting,
  AdminUserUpdateRequest,
  SystemSettingsUpdateRequest,
} from '$lib/types';
import { apiClient } from './client';

// Re-export types for convenience
export type { SystemSetting, AdminUserUpdateRequest, SystemSettingsUpdateRequest };

export const adminApi = {
  /**
   * List all users (superuser only)
   */
  listUsers: async (params?: {
    page?: number;
    limit?: number;
    search?: string;
    is_active?: boolean;
  }): Promise<AdminUserListResponse> => {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.set('page', params.page.toString());
    if (params?.limit) queryParams.set('limit', params.limit.toString());
    if (params?.search) queryParams.set('search', params.search);
    if (params?.is_active !== undefined) queryParams.set('is_active', params.is_active.toString());

    const query = queryParams.toString();
    const endpoint = `/api/v1/admin/users${query ? `?${query}` : ''}`;

    return apiClient.get<AdminUserListResponse>(endpoint);
  },

  /**
   * Update user (superuser only)
   */
  updateUser: async (userId: string, data: AdminUserUpdateRequest): Promise<User> => {
    return apiClient.patch<User>(`/api/v1/admin/users/${userId}`, data);
  },

  /**
   * Get system settings (superuser only)
   */
  getSystemSettings: async (): Promise<Record<string, SystemSetting>> => {
    return apiClient.get<Record<string, SystemSetting>>('/api/v1/admin/settings');
  },

  /**
   * Update system settings (superuser only)
   */
  updateSystemSettings: async (data: SystemSettingsUpdateRequest): Promise<void> => {
    return apiClient.patch<void>('/api/v1/admin/settings', data);
  },
};
