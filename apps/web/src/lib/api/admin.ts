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
const STEP_UP_HEADER_NAME = 'X-Step-Up-Token';

/**
 * spec/011 US4 — admin password reset response.
 *
 * The temporary password is only ever returned once (Cache-Control:
 * no-store on the backend); the caller must surface it immediately and
 * never persist it. `expires_at` is 24h from issue.
 */
export interface AdminResetPasswordResponse {
  temporary_password: string;
  expires_at: string;
}

/**
 * Common response for the superuser taxon maintenance dispatch endpoints
 * (`seed-birdnet` / `sync-vernacular`).
 *
 * Both endpoints enqueue a Celery task and return immediately (no body work
 * done inline), mirroring the IUCN force-resync dispatch contract:
 * `task_id` is the Celery task id and `enqueued_at` is the ISO-8601 UTC
 * timestamp the task was queued.
 */
export interface TaxonMaintenanceDispatchResponse {
  task_id: string;
  enqueued_at: string;
}

/**
 * Response for the IUCN force-resync dispatch
 * (`POST /admin/iucn/force-resync`).
 *
 * The endpoint is fire-and-forget: it enqueues the `sync_iucn_red_list`
 * Celery task and returns immediately. `task_id` is the Celery task id and
 * `enqueued_at` is the ISO-8601 UTC dispatch timestamp. There is no
 * task-status polling surface — the operator correlates the id with the
 * worker's own `IucnSyncAttempt` progress rows.
 */
export interface IucnForceResyncResponse {
  task_id: string;
  enqueued_at: string;
}

/**
 * Snapshot of a wedged upload session surfaced by the admin recovery
 * endpoints (`GET /admin/uploads/stuck` list + `POST /admin/uploads/{id}/fail`
 * post-action single). `project_id` is resolved via the session's parent
 * dataset (the session row has no direct project FK).
 */
export interface StuckUploadSessionSummary {
  id: string;
  dataset_id: string;
  project_id: string;
  status: string;
  error: string | null;
  total_files: number;
  validated_files: number;
  imported_files: number;
  created_at: string;
  updated_at: string;
}

/**
 * Body for `GET /admin/uploads/stuck` — a page of stuck (non-terminal)
 * upload sessions, oldest first.
 */
export interface StuckUploadSessionListResponse {
  items: StuckUploadSessionSummary[];
}

/**
 * Query parameters for the stuck-upload listing.
 *
 * All optional; omitting them lets the backend apply its defaults.
 * `older_than_seconds` filters to sessions whose last progress tick is at
 * least this old; `limit`/`offset` paginate.
 */
export interface StuckUploadListParams {
  older_than_seconds?: number;
  limit?: number;
  offset?: number;
}

/**
 * Request body for the vernacular-name sync dispatch.
 *
 * All fields are optional; omitting them lets the backend apply its
 * defaults (`batch_size=100`, `locales=null` → all configured locales,
 * `skip_existing=true`).
 */
export interface SyncVernacularRequest {
  batch_size?: number;
  locales?: string[] | null;
  skip_existing?: boolean;
}

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

  /**
   * spec/011 US4 — reset a user's password to a temporary credential
   * (superuser only, step-up gated).
   *
   * Requires a fresh `admin_recovery`-scoped step-up token (obtained via
   * `stepUpBegin` / `stepUpComplete`) attached as `X-Step-Up-Token`. The
   * body is intentionally empty — the v1 contract omits the reason
   * field. Returns the one-time temporary password + its 24h expiry.
   */
  resetUserPassword: async (
    userId: string,
    stepUpToken: string
  ): Promise<AdminResetPasswordResponse> => {
    return apiClient.post<AdminResetPasswordResponse>(
      `${WEB_API_BASE}/admin/users/${userId}/reset-password`,
      {},
      {
        headers: {
          ...csrfHeaders(),
          [STEP_UP_HEADER_NAME]: stepUpToken,
        },
      }
    );
  },

  /**
   * Dispatch the BirdNET taxon seed task (superuser only).
   *
   * Enqueues a Celery task that materialises the ~1000 BirdNET species into
   * the local taxonomy. Idempotent — re-running skips taxa that already
   * exist. The request body is intentionally empty; mirrors the IUCN
   * force-resync dispatch shape.
   */
  seedBirdnetTaxa: async (): Promise<TaxonMaintenanceDispatchResponse> => {
    return apiClient.post<TaxonMaintenanceDispatchResponse>(
      `${WEB_API_BASE}/admin/taxon/seed-birdnet`,
      {},
      { headers: csrfHeaders() }
    );
  },

  /**
   * Dispatch the vernacular-name sync task (superuser only).
   *
   * Enqueues a Celery task that fetches/refreshes locale-specific vernacular
   * names (e.g. 和名) for existing taxa. All body fields are optional and
   * fall back to backend defaults when omitted.
   */
  syncVernacularNames: async (
    data?: SyncVernacularRequest
  ): Promise<TaxonMaintenanceDispatchResponse> => {
    return apiClient.post<TaxonMaintenanceDispatchResponse>(
      `${WEB_API_BASE}/admin/taxon/sync-vernacular`,
      data ?? {},
      { headers: csrfHeaders() }
    );
  },

  /**
   * Dispatch the IUCN Red List force-resync task (superuser only).
   *
   * Enqueues the `sync_iucn_red_list` Celery task and returns immediately.
   * The request body is intentionally empty; mirrors the taxon maintenance
   * dispatch shape. Fire-and-forget — there is no task-status polling
   * surface; the returned `task_id` correlates with the worker's own
   * progress rows.
   */
  forceIucnResync: async (): Promise<IucnForceResyncResponse> => {
    return apiClient.post<IucnForceResyncResponse>(
      `${WEB_API_BASE}/admin/iucn/force-resync`,
      {},
      { headers: csrfHeaders() }
    );
  },

  /**
   * List stuck (non-terminal) upload sessions (superuser only).
   *
   * Returns wedged sessions oldest first so a superuser can inspect and
   * recover them. All query parameters are optional and fall back to
   * backend defaults when omitted.
   */
  listStuckUploads: async (
    params?: StuckUploadListParams
  ): Promise<StuckUploadSessionListResponse> => {
    const queryParams = new URLSearchParams();
    if (params?.older_than_seconds !== undefined) {
      queryParams.set('older_than_seconds', params.older_than_seconds.toString());
    }
    if (params?.limit !== undefined) {
      queryParams.set('limit', params.limit.toString());
    }
    if (params?.offset !== undefined) {
      queryParams.set('offset', params.offset.toString());
    }

    const query = queryParams.toString();
    const endpoint = `${WEB_API_BASE}/admin/uploads/stuck${query ? `?${query}` : ''}`;

    return apiClient.get<StuckUploadSessionListResponse>(endpoint);
  },

  /**
   * Force-fail a stuck upload session (superuser only).
   *
   * Transitions a wedged session to a terminal `failed` state and returns
   * the updated session summary. The backend responds 404 for an unknown
   * session and 409 when the session is already terminal or transitioned
   * concurrently — callers should surface the 409 detail message (it is
   * informative, not a bug: the session may have completed on its own).
   */
  forceFailUpload: async (
    sessionId: string
  ): Promise<StuckUploadSessionSummary> => {
    return apiClient.post<StuckUploadSessionSummary>(
      `${WEB_API_BASE}/admin/uploads/${sessionId}/fail`,
      {},
      { headers: csrfHeaders() }
    );
  },
};
