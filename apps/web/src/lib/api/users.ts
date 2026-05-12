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
 * Get current user profile.
 *
 * Reads via the BFF cookie + CSRF surface at ``/web-api/v1/users/me``
 * so browser sessions established by the post-spec/006 web-auth flow
 * (cookie-only, no Bearer header) succeed. The legacy
 * ``/api/v1/users/me`` Bearer-JWT path is still served by
 * :mod:`echoroo.api.v1.users` for programmatic / API-token callers,
 * but browser callers must use the BFF mirror to avoid the
 * auto-logout regression.
 */
export async function getCurrentUser(): Promise<User> {
  return apiClient.get<User>('/web-api/v1/users/me');
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
