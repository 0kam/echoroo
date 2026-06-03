/**
 * Projects API endpoints
 */

import type {
  Project,
  ProjectMember,
  ProjectSummaryListResponse,
  ProjectCreateRequest,
  ProjectUpdateRequest,
  ProjectMemberUpdateRequest,
  TransferOwnershipResponse,
  ProjectOverviewResponse,
  RestrictedConfigUpdateRequest,
  TrustedUserInviteRequest,
  TrustedUserInviteResponse,
  TrustedUserListResponse,
  TrustedUser,
  TrustedUserUpdateRequest,
  ProjectTrustedStatus,
  InvitationAcceptResponse,
  ProjectCreateResponse,
  MemberInvitationIssueRequest,
  MemberInvitationIssueResponse,
  BulkInvitationRequest,
  BulkInvitationResultItem,
  ProjectInvitationListResponse,
  InvitationRevokeRequest,
  InvitationRevokeResponse,
} from '$lib/types';
import { ApiError, apiClient } from './client';
import { localizeHref } from '$lib/paraglide/runtime';

/**
 * Build the full, user-facing invitation acceptance URL from a raw signed
 * token envelope.
 *
 * The issue endpoints (`issueInvitation` / `bulkInvite`) return
 * `invitation_url` as a RAW signed token string (e.g.
 * `c_AbC...1781056121.preview-v1.XyZ...`), NOT a full URL: behind SSH
 * port-forwarding the backend cannot know the user-facing host, so the
 * admin's own browser `origin` is the only correct shareable host.
 *
 * The path resolves to the public `(public)/invite/[token]` acceptance
 * page. We run the relative path through `localizeHref` first so the URL
 * respects the project's URL-based locale routing (`/en/...` | `/ja/...`),
 * then prefix the current `window.location.origin` to produce an absolute,
 * copy-pasteable link.
 *
 * On the server (no `window`) we fall back to the relative localized path;
 * in practice this helper is only ever called in the browser after an
 * invitation is issued.
 */
export function buildInviteUrl(token: string): string {
  const localizedPath = localizeHref(`/invite/${encodeURIComponent(token)}`);
  if (typeof window === 'undefined') {
    return localizedPath;
  }
  // `localizedPath` is relative (starts with `/`); `URL` resolves it
  // against the origin to yield an absolute, shareable URL.
  return new URL(localizedPath, window.location.origin).href;
}

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

async function getAccessTokenForWebApi(): Promise<string | null> {
  const existingToken = apiClient.getAccessToken();
  if (existingToken) return existingToken;

  try {
    await apiClient.refreshToken();
  } catch {
    // Let the protected Web API request below surface the canonical
    // backend auth error when refresh cookies are absent or expired.
  }

  return apiClient.getAccessToken();
}

/**
 * Issue a request to a private `/web-api/v1/...` endpoint with the
 * first-party session cookie, Bearer access token, and CSRF token.
 *
 * The shared `apiClient` is Bearer-token-oriented and was built for the
 * general request surface; these project Web UI endpoints additionally
 * require the `X-CSRF-Token` header sourced from the `echoroo_csrf`
 * cookie for any non-safe verb. Promoted to a shared helper in Phase 10
 * (T520 / T521) so the Trusted overlay management + invitation accept
 * flow can reuse the same envelope-aware error extraction logic.
 *
 * @param method Standard HTTP verb. The body is omitted automatically
 *               for safe verbs (GET / HEAD / DELETE).
 * @param path   Path under `/web-api/v1` (e.g. `/projects/{id}/trusted-users`).
 * @param body   Request body. Stringified with `JSON.stringify`. Pass
 *               `undefined` to send no body (e.g. POST accept which only
 *               needs an idempotency header, or DELETE which never has
 *               a body).
 * @param extraHeaders Caller-supplied headers. Merged AFTER the default
 *               headers so the caller can override (e.g. set
 *               `X-Idempotency-Key` for FR-053 accept).
 */
export async function callWebApi<T>(
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>
): Promise<T> {
  const url = `${resolveBaseUrl()}/web-api/v1${path}`;
  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  const accessToken = await getAccessTokenForWebApi();
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const csrfToken = getCsrfToken();
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  if (extraHeaders) {
    for (const [k, v] of Object.entries(extraHeaders)) {
      headers[k] = v;
    }
  }

  const init: RequestInit = {
    method,
    credentials: 'include',
    headers,
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }

  const response = await fetch(url, init);

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

/**
 * Backwards-compatible alias for the Phase 8 PATCH helper. Still used
 * by ``updateRestrictedConfig`` so the call-site stays terse.
 */
async function patchWebApi<T>(path: string, body: unknown): Promise<T> {
  return callWebApi<T>('PATCH', path, body);
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
  list: async (params?: { page?: number; limit?: number }): Promise<ProjectSummaryListResponse> => {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.set('page', params.page.toString());
    if (params?.limit) queryParams.set('limit', params.limit.toString());

    const query = queryParams.toString();
    const endpoint = `/web-api/v1/projects/${query ? `?${query}` : ''}`;

    return apiClient.get<ProjectSummaryListResponse>(endpoint);
  },

  /**
   * Get a single project by ID
   */
  get: async (projectId: string): Promise<Project> => {
    return apiClient.get<Project>(`/web-api/v1/projects/${projectId}`);
  },

  /**
   * Create a new project.
   *
   * The SU-bootstrap redesign (preview feedback #1) dropped the create-time
   * `intended_owner_email` flow, so the response is now the plain `Project`
   * shape (`ProjectCreateResponse = Project`). Post-creation ownership
   * transfer is handled separately via `transferOwnership()`.
   */
  create: async (data: ProjectCreateRequest): Promise<ProjectCreateResponse> => {
    return callWebApi<ProjectCreateResponse>('POST', '/projects/', data);
  },

  /**
   * Transfer project ownership to an active project Admin (preview
   * feedback #2 / SU-bootstrap redesign).
   *
   * `POST /web-api/v1/projects/{id}/transfer-ownership` — Owner-only.
   * The body carries the target `new_owner_user_id`; the required
   * `X-Idempotency-Key` header makes the call replay-safe (a double-click
   * cannot transfer twice). On success the previous owner is demoted to
   * Admin and the target is promoted to Owner.
   *
   * Backend error codes surface via `ApiError`:
   * - 400 `ERR_INVALID_TRANSFER_TARGET` — target is no longer an active Admin.
   * - 409 — idempotency conflict / concurrent transfer.
   */
  transferOwnership: async (
    projectId: string,
    newOwnerUserId: string,
    idempotencyKey: string
  ): Promise<TransferOwnershipResponse> => {
    return callWebApi<TransferOwnershipResponse>(
      'POST',
      `/projects/${projectId}/transfer-ownership`,
      { new_owner_user_id: newOwnerUserId },
      { 'X-Idempotency-Key': idempotencyKey }
    );
  },

  /**
   * Update a project (admin only)
   */
  update: async (projectId: string, data: ProjectUpdateRequest): Promise<Project> => {
    return callWebApi<Project>('PATCH', `/projects/${projectId}`, data);
  },

  /**
   * Delete a project (owner only)
   */
  delete: async (projectId: string): Promise<void> => {
    await callWebApi<void>('DELETE', `/projects/${projectId}`);
  },

  /**
   * List project members
   */
  listMembers: async (projectId: string): Promise<ProjectMember[]> => {
    return callWebApi<ProjectMember[]>('GET', `/projects/${projectId}/members`);
  },

  /**
   * Update member role (admin only)
   */
  updateMemberRole: async (
    projectId: string,
    userId: string,
    data: ProjectMemberUpdateRequest
  ): Promise<ProjectMember> => {
    return callWebApi<ProjectMember>(
      'PATCH',
      `/projects/${projectId}/members/${userId}`,
      data
    );
  },

  /**
   * Remove a member from the project (admin only)
   */
  removeMember: async (projectId: string, userId: string): Promise<void> => {
    await callWebApi<void>('DELETE', `/projects/${projectId}/members/${userId}`);
  },

  /**
   * Get project overview (sites, recording calendar, stats)
   */
  getOverview: async (projectId: string): Promise<ProjectOverviewResponse> => {
    return callWebApi<ProjectOverviewResponse>('GET', `/projects/${projectId}/overview`);
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

  /**
   * List Trusted overlays for a project (Phase 10 / T520, FR-050).
   *
   * Owner / Admin only. The optional ``status`` filter narrows the
   * result to ``active`` / ``expired`` / ``revoked``. Members / Viewers
   * receive a 403 from the backend, which surfaces as
   * ``ApiError(status=403)`` for the caller to handle.
   */
  listTrustedUsers: async (
    projectId: string,
    status?: ProjectTrustedStatus
  ): Promise<TrustedUserListResponse> => {
    const query = status ? `?status=${encodeURIComponent(status)}` : '';
    return callWebApi<TrustedUserListResponse>(
      'GET',
      `/projects/${projectId}/trusted-users${query}`
    );
  },

  /**
   * Issue a Trusted invitation (Phase 10 / T520, FR-050).
   *
   * Owner-only. Backend errors surface via ``ApiError.code``:
   *
   * - 422 ``ERR_SELF_TRUSTED_INVALID`` — owner targeted self.
   * - 422 ``ERR_TRUSTED_TARGET_INVALID`` — target already has a project role.
   * - 422 ``ERR_INVALID_TRUSTED_PERMISSION`` — granted_permissions outside
   *   ``TRUSTED_ALLOWED_PERMISSIONS``.
   * - 409 ``ERR_INVITATION_PENDING`` — pending invitation already exists.
   */
  inviteTrustedUser: async (
    projectId: string,
    body: TrustedUserInviteRequest
  ): Promise<TrustedUserInviteResponse> => {
    return callWebApi<TrustedUserInviteResponse>(
      'POST',
      `/projects/${projectId}/trusted-users`,
      body
    );
  },

  /**
   * Extend / edit a Trusted overlay (Phase 10 / T520, FR-046).
   *
   * Owner-only. Empty body is rejected with 422 ``ERR_NO_OP``. Per the
   * trusted contract (Round 2 polish, Major 4) only ``expires_at`` and
   * ``granted_permissions`` are accepted; the absolute ISO datetime is
   * the canonical representation of an extension.
   */
  updateTrustedUser: async (
    projectId: string,
    trustedUserId: string,
    body: TrustedUserUpdateRequest
  ): Promise<TrustedUser> => {
    return callWebApi<TrustedUser>(
      'PATCH',
      `/projects/${projectId}/trusted-users/${trustedUserId}`,
      body
    );
  },

  /**
   * Revoke a Trusted overlay (Phase 10 / T520, FR-046).
   *
   * Owner-only. Idempotent (revoking an already-revoked overlay still
   * returns 204).
   */
  revokeTrustedUser: async (projectId: string, trustedUserId: string): Promise<void> => {
    await callWebApi<void>('DELETE', `/projects/${projectId}/trusted-users/${trustedUserId}`);
  },

  /**
   * Accept an invitation (Phase 10 / T521, FR-053 / FR-054).
   *
   * Required header ``X-Idempotency-Key`` — replays under the same key
   * return the same outcome (200) so a double-click cannot create
   * duplicate memberships. Backend error codes:
   *
   * - 403 ``ERR_EMAIL_MISMATCH`` — caller's email differs from the
   *   invitation's stored hash.
   * - 404 ``invitation not found`` — token unknown / project mismatch.
   * - 410 ``ERR_INVITATION_TERMINAL_STATE`` — already accepted / expired
   *   / revoked.
   * - 409 ``ERR_INVITATION_CONFLICT`` — same idempotency key replayed
   *   with a different token.
   * - 503 — Redis idempotency cache unreachable.
   */
  acceptInvitation: async (
    projectId: string,
    token: string,
    idempotencyKey: string
  ): Promise<InvitationAcceptResponse> => {
    return callWebApi<InvitationAcceptResponse>(
      'POST',
      `/projects/${projectId}/invitations/${encodeURIComponent(token)}/accept`,
      undefined,
      { 'X-Idempotency-Key': idempotencyKey }
    );
  },

  /**
   * Recipient-driven self-decline (Phase 10 / T521, FR-107).
   *
   * Idempotent: an already-declined invitation still returns 204. All
   * "cannot resolve / cannot match" outcomes (token unknown, email
   * mismatch, cross-account) collapse to 404 per FR-055; terminal
   * states (accepted / expired / revoked) return 410.
   */
  declineInvitation: async (projectId: string, token: string): Promise<void> => {
    await callWebApi<void>(
      'DELETE',
      `/projects/${projectId}/invitations/${encodeURIComponent(token)}`
    );
  },

  /**
   * Issue a single project member invitation (spec/011 US6 plumbing).
   *
   * `POST /projects/{id}/invitations` → 201 `MemberInvitationIssueResponse`.
   * The returned `invitation_url` is one-shot and cannot be recovered
   * after this response is consumed. No UI consumer in this PR — exported
   * to unblock the future collaborators page.
   *
   * Backend error codes surface via `ApiError.code` (e.g. 409
   * `ERR_INVITATION_PENDING`).
   */
  issueInvitation: async (
    projectId: string,
    body: MemberInvitationIssueRequest
  ): Promise<MemberInvitationIssueResponse> => {
    return callWebApi<MemberInvitationIssueResponse>(
      'POST',
      `/projects/${projectId}/invitations`,
      body
    );
  },

  /**
   * List project invitations (spec/011 US6 plumbing).
   *
   * `GET /projects/{id}/invitations?kind=&status=` →
   * `ProjectInvitationListResponse`. Both filters are optional and only
   * appended to the query string when supplied. No UI consumer in this
   * PR — exported to unblock the future collaborators page.
   */
  listInvitations: async (
    projectId: string,
    opts?: { kind?: string; status?: string }
  ): Promise<ProjectInvitationListResponse> => {
    const queryParams = new URLSearchParams();
    if (opts?.kind) queryParams.set('kind', opts.kind);
    if (opts?.status) queryParams.set('status', opts.status);
    const query = queryParams.toString();
    return callWebApi<ProjectInvitationListResponse>(
      'GET',
      `/projects/${projectId}/invitations${query ? `?${query}` : ''}`
    );
  },

  /**
   * Bulk-issue project member invitations (spec/011 US6 plumbing).
   *
   * `POST /projects/{id}/invitations/bulk` → 207 multi-status array of
   * `BulkInvitationResultItem`. A 207 is `response.ok`, so `callWebApi`
   * parses the body normally; per-email outcomes are encoded in each
   * element's `status` (`issued` / `duplicate_pending` / `rate_limited`
   * / `internal_error`). No UI consumer in this PR — exported to unblock
   * the future collaborators page.
   */
  bulkInvite: async (
    projectId: string,
    body: BulkInvitationRequest
  ): Promise<BulkInvitationResultItem[]> => {
    return callWebApi<BulkInvitationResultItem[]>(
      'POST',
      `/projects/${projectId}/invitations/bulk`,
      body
    );
  },

  /**
   * Revoke a pending project invitation (spec/011 US6 plumbing).
   *
   * `POST /projects/{id}/invitations/{invitation_id}/revoke` →
   * `InvitationRevokeResponse`. The optional `reason` is recorded for the
   * audit trail. No UI consumer in this PR — exported to unblock the
   * future collaborators page.
   */
  revokeInvitation: async (
    projectId: string,
    invitationId: string,
    body?: InvitationRevokeRequest
  ): Promise<InvitationRevokeResponse> => {
    return callWebApi<InvitationRevokeResponse>(
      'POST',
      `/projects/${projectId}/invitations/${encodeURIComponent(invitationId)}/revoke`,
      body ?? {}
    );
  },
};
