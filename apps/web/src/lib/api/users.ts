/**
 * Users API client
 * Handles user profile operations
 */

import { apiClient } from './client';
import type {
  User,
  UserUpdateRequest,
  PasswordChangeRequest,
} from '$lib/types';

// Re-export types for convenience
export type { UserUpdateRequest, PasswordChangeRequest };

// Legacy type exports (deprecated, for backwards compatibility)
/**
 * @deprecated Use UserUpdateRequest from $lib/types instead
 */
export type UpdateUserRequest = UserUpdateRequest;

/**
 * @deprecated Use PasswordChangeRequest from $lib/types instead
 */
export type ChangePasswordRequest = PasswordChangeRequest;

/**
 * Password change response
 */
export interface PasswordChangeResponse {
  message: string;
}

/**
 * Get current user profile
 */
export async function getCurrentUser(): Promise<User> {
  return apiClient.get<User>('/api/v1/users/me');
}

/**
 * Update current user profile
 */
export async function updateUser(data: UserUpdateRequest): Promise<User> {
  return apiClient.patch<User>('/api/v1/users/me', data);
}

/**
 * Change password for current user
 */
export async function changePassword(data: PasswordChangeRequest): Promise<PasswordChangeResponse> {
  return apiClient.request<PasswordChangeResponse>('/api/v1/users/me/password', {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}
