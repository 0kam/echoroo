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
 * Update current user profile.
 *
 * Mutates via the BFF cookie + CSRF surface at
 * ``/web-api/v1/users/me`` (W2-2). The legacy ``/api/v1/users/me``
 * Bearer-JWT path stays live for programmatic / API-token callers.
 */
export async function updateUser(data: UserUpdateRequest): Promise<User> {
  return apiClient.patch<User>('/web-api/v1/users/me', data, {
    headers: csrfHeaders(),
  });
}

/**
 * Change password for current user (voluntary /settings flow).
 *
 * Mutates via the BFF cookie + CSRF surface at
 * ``/web-api/v1/users/me/password`` (W2-2). This is the simple
 * voluntary change-password path; the spec/011 forced-change flow lives
 * on ``/web-api/v1/auth/change-password`` (see ``auth.ts``).
 */
export async function changePassword(data: PasswordChangeRequest): Promise<PasswordChangeResponse> {
  return apiClient.request<PasswordChangeResponse>('/web-api/v1/users/me/password', {
    method: 'PUT',
    body: JSON.stringify(data),
    headers: csrfHeaders(),
  });
}
