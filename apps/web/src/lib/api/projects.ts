/**
 * Projects API endpoints
 */

import type {
  Project,
  ProjectMember,
  ProjectSummaryListResponse,
  ProjectCreateRequest,
  ProjectUpdateRequest,
  ProjectMemberAddRequest,
  ProjectMemberUpdateRequest,
  ProjectOverviewResponse,
  RestrictedConfigUpdateRequest,
} from '$lib/types';
import { ApiError } from './client';
import { apiClient } from './client';

/**
 * CSRF cookie name shared with the backend
 * (`settings.web_csrf_cookie_name`). Keep in sync with
 * `apps/web/src/lib/api/web-auth.ts`.
 */
const CSRF_COOKIE_NAME = 'echoroo_csrf';

/**
 * Read the CSRF token from `document.cookie`. Returns `null` on the
 * server (no `document`) or when the cookie is absent. The cookie is
 * set with `httponly=False` so browser JS can read it.
 */
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

/**
 * Resolve the API base URL the same way the shared `apiClient` does:
 * relative URLs in the browser (so requests pass through the Vite
 * proxy) and an explicit URL on the server.
 */
function resolveBaseUrl(): string {
  if (typeof window !== 'undefined') {
    return '';
  }
  return import.meta.env.PUBLIC_API_URL || 'http://localhost:8002';
}

/**
 * PATCH a `/web-api/v1/...` endpoint with cookie-based session + CSRF.
 *
 * The shared `apiClient` is Bearer-token-oriented and was built for the
 * legacy `/api/v1/*` surface; the restricted-config Web UI endpoint
 * lives under `/web-api/v1/*` which requires the `X-CSRF-Token` header
 * sourced from the `echoroo_csrf` cookie. We keep this helper local to
 * `projects.ts` for now because it is the only non-auth Web UI mutation
 * the frontend needs in Phase 8; if more land in later phases we can
 * promote it to a shared module.
 */
async function patchWebApi<T>(path: string, body: unknown): Promise<T> {
  const url = `${resolveBaseUrl()}/web-api/v1${path}`;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  // Forward the access-token Bearer alongside the cookie (defence in depth):
  // the backend route resolves the principal via OptionalCurrentUser which
  // accepts either credential type. The cookie path is the production one
  // — Bearer is mostly a Vitest fallback.
  const token = apiClient.getAccessToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const csrfToken = getCsrfToken();
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;

  const response = await fetch(url, {
    method: 'PATCH',
    credentials: 'include',
    headers,
    body: JSON.stringify(body ?? {}),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
    // The backend wraps the structured envelope inside `detail` for some
    // routes (HTTPException with dict detail) and at the top level for
    // others — accept both shapes when extracting the error code.
    const obj =
      typeof errorData === 'object' && errorData !== null
        ? (errorData as Record<string, unknown>)
        : {};
    const detailObj =
      typeof obj.detail === 'object' && obj.detail !== null
        ? (obj.detail as Record<string, unknown>)
        : null;
    const code =
      (typeof obj.error === 'string' && obj.error) ||
      (typeof obj.code === 'string' && obj.code) ||
      (detailObj && typeof detailObj.error === 'string' && detailObj.error) ||
      null;
    const message =
      (detailObj && typeof detailObj.message === 'string' && detailObj.message) ||
      (typeof obj.message === 'string' && obj.message) ||
      (typeof obj.detail === 'string' && obj.detail) ||
      'Request failed';
    throw new ApiError(message, response.status, message, code || null);
  }

  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type');
  if (contentType?.includes('application/json')) {
    return (await response.json()) as T;
  }
  return {} as T;
}

export const projectsApi = {
  /**
   * List all projects accessible to the current user.
   *
   * Phase 9 / FR-018, FR-019: the backend returns
   * `ProjectSummaryListResponse` (`{ items: ProjectSummary[]; total;
   * page }`) — **not** the legacy full-`Project` paginated shape.
   * Restricted projects' metadata is included for Guest / Authenticated
   * non-members but `restricted_config` and the full `owner` sub-object
   * never reach the wire.
   *
   * The `limit` query parameter is still accepted by the backend for
   * page-size selection, but the response itself does not echo it back
   * (contract only declares `items / total / page`).
   */
  list: async (params?: {
    page?: number;
    limit?: number;
  }): Promise<ProjectSummaryListResponse> => {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.set('page', params.page.toString());
    if (params?.limit) queryParams.set('limit', params.limit.toString());

    const query = queryParams.toString();
    const endpoint = `/api/v1/projects${query ? `?${query}` : ''}`;

    return apiClient.get<ProjectSummaryListResponse>(endpoint);
  },

  /**
   * Get a single project by ID
   */
  get: async (projectId: string): Promise<Project> => {
    return apiClient.get<Project>(`/api/v1/projects/${projectId}`);
  },

  /**
   * Create a new project
   */
  create: async (data: ProjectCreateRequest): Promise<Project> => {
    return apiClient.post<Project>('/api/v1/projects', data);
  },

  /**
   * Update a project (admin only)
   */
  update: async (projectId: string, data: ProjectUpdateRequest): Promise<Project> => {
    return apiClient.patch<Project>(`/api/v1/projects/${projectId}`, data);
  },

  /**
   * Delete a project (owner only)
   */
  delete: async (projectId: string): Promise<void> => {
    return apiClient.delete<void>(`/api/v1/projects/${projectId}`);
  },

  /**
   * List project members
   */
  listMembers: async (projectId: string): Promise<ProjectMember[]> => {
    return apiClient.get<ProjectMember[]>(`/api/v1/projects/${projectId}/members`);
  },

  /**
   * Add a member to the project (admin only)
   */
  addMember: async (projectId: string, data: ProjectMemberAddRequest): Promise<ProjectMember> => {
    return apiClient.post<ProjectMember>(`/api/v1/projects/${projectId}/members`, data);
  },

  /**
   * Update member role (admin only)
   */
  updateMemberRole: async (
    projectId: string,
    userId: string,
    data: ProjectMemberUpdateRequest
  ): Promise<ProjectMember> => {
    return apiClient.patch<ProjectMember>(
      `/api/v1/projects/${projectId}/members/${userId}`,
      data
    );
  },

  /**
   * Remove a member from the project (admin only)
   */
  removeMember: async (projectId: string, userId: string): Promise<void> => {
    return apiClient.delete<void>(`/api/v1/projects/${projectId}/members/${userId}`);
  },

  /**
   * Get project overview (sites, recording calendar, stats)
   */
  getOverview: async (projectId: string): Promise<ProjectOverviewResponse> => {
    return apiClient.get<ProjectOverviewResponse>(`/api/v1/projects/${projectId}/overview`);
  },

  /**
   * Update Restricted-mode capability toggles (Phase 8 / T400, FR-014).
   *
   * Posts the full `RestrictedConfig` shape to
   * `PATCH /web-api/v1/projects/{id}/restricted-config` (cookie + CSRF).
   *
   * Error codes the UI must branch on:
   *   - 422 + `code === 'ERR_RESTRICTED_CONFIG_NOT_APPLICABLE'`
   *     → the project's `visibility` is `public`; toggles do not apply.
   *   - 403 → caller lacks `EDIT_PROJECT` (Member / Viewer / non-member).
   *   - 401 → caller is unauthenticated.
   */
  updateRestrictedConfig: async (
    projectId: string,
    config: RestrictedConfigUpdateRequest
  ): Promise<Project> => {
    return patchWebApi<Project>(`/projects/${projectId}/restricted-config`, config);
  },
};
