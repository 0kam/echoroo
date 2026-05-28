/**
 * Admin API endpoints.
 *
 * spec/009 PR 5: the four superuser surfaces (list/update users, get/update
 * system settings) now resolve through the cookie + CSRF BFF mount
 * (`/web-api/v1/admin/*`). The legacy `/api/v1/admin/*` route stays live
 * for M2M API-key callers, but cookie-session admins must go through the
 * BFF or the AuthRouter middleware rejects the request with 401 →
 * auto-logout. Mutations attach `X-CSRF-Token` via the inline
 * `csrfHeaders()` helper used by every other migrated BFF module.
 */

import type {
  AdminUserListItem,
  AdminUserListResponse,
  SystemSetting,
  AdminUserUpdateRequest,
  SystemSettingsUpdateRequest,
} from '$lib/types';
import { apiClient } from './client';

// Re-export types for convenience
export type { SystemSetting, AdminUserUpdateRequest, SystemSettingsUpdateRequest };

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

export const adminApi = {
  /**
   * List all users (superuser only).
   *
   * spec/006 + spec/011: the ``is_active`` query parameter was removed
   * along with the persisted ``users.is_active`` column. Filtering is
   * limited to the free-text ``search`` term against email + display
   * name.
   */
  listUsers: async (params?: {
    page?: number;
    limit?: number;
    search?: string;
  }): Promise<AdminUserListResponse> => {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.set('page', params.page.toString());
    if (params?.limit) queryParams.set('limit', params.limit.toString());
    if (params?.search) queryParams.set('search', params.search);

    const query = queryParams.toString();
    const endpoint = `${WEB_API_BASE}/admin/users${query ? `?${query}` : ''}`;

    return apiClient.get<AdminUserListResponse>(endpoint);
  },

  /**
   * Update user (superuser only).
   *
   * The backend currently only honours ``display_name``; legacy
   * ``is_active`` / ``is_superuser`` / ``is_verified`` payload fields
   * are accepted but silently ignored (see
   * :type:`AdminUserUpdateRequest`). Superuser promotion lives in the
   * ``/admin/superusers`` M-of-N flow.
   */
  updateUser: async (
    userId: string,
    data: AdminUserUpdateRequest
  ): Promise<AdminUserListItem> => {
    return apiClient.patch<AdminUserListItem>(
      `${WEB_API_BASE}/admin/users/${userId}`,
      data,
      { headers: csrfHeaders() }
    );
  },

  /**
   * Get system settings (superuser only)
   */
  getSystemSettings: async (): Promise<Record<string, SystemSetting>> => {
    return apiClient.get<Record<string, SystemSetting>>(`${WEB_API_BASE}/admin/settings`);
  },

  /**
   * Update system settings (superuser only)
   */
  updateSystemSettings: async (data: SystemSettingsUpdateRequest): Promise<void> => {
    return apiClient.patch<void>(
      `${WEB_API_BASE}/admin/settings`,
      data,
      { headers: csrfHeaders() }
    );
  },
};
