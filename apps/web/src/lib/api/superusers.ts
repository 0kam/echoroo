/**
 * Superuser admin API client (Phase 15 / 006-permissions-redesign T955).
 *
 * Talks to the cookie-session protected `/web-api/v1/admin/superusers/*`
 * endpoints. All POST / PATCH calls attach `X-CSRF-Token` from the
 * `echoroo_csrf` cookie just like the rest of the web-auth router.
 *
 * Programmatic API keys are forbidden by the backend (FR-084): every call
 * is issued via the shared :data:`apiClient` so the user's session cookie
 * + Bearer access token carry the authorization decision, and stale tokens
 * trigger the same auto-refresh-on-401 flow the rest of the BFF surface
 * uses. Without auto-refresh, a stale access cookie produced a 401 on
 * every superuser page load and surfaced as "Access token required" in
 * the UI banner.
 */

import { ApiError, apiClient } from './client';
import { getActiveStepUpToken } from '$lib/utils/webauthnGating';

const BASE = '/web-api/v1/admin';
const CSRF_COOKIE_NAME = 'echoroo_csrf';
const STEP_UP_HEADER_NAME = 'X-Step-Up-Token';

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
 * Build the header bag for a destructive ``/superusers/*`` mutation.
 *
 * Phase 16 Batch 6g-3 wires a WebAuthn step-up gate in front of every
 * destructive admin endpoint; the cached token is attached here so the
 * backend ``require_step_up_token`` dependency clears. Missing token →
 * backend 401 ``step_up_token_required`` which the UI translates into a
 * re-prompt for the ceremony.
 */
function mutationHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const csrf = getCsrfToken();
  if (csrf) headers['X-CSRF-Token'] = csrf;
  const stepUp = getActiveStepUpToken();
  if (stepUp) headers[STEP_UP_HEADER_NAME] = stepUp;
  return headers;
}

// ---------- Types ----------

export interface SuperuserSummary {
  id: string;
  user_id: string;
  added_by_id: string | null;
  added_at: string;
  revoked_at: string | null;
  allowed_ip_cidrs: string[];
  webauthn_credential_count: number;
}

export interface SuperuserListResponse {
  items: SuperuserSummary[];
  active_count: number;
  min_superusers: number;
  break_glass_active: boolean;
}

export interface SuperuserAddRequest {
  target_user_id: string;
  allowed_ip_cidrs?: string[];
}

export type SuperuserActionStatus = 'direct' | 'pending' | 'applied' | 'rejected';

export interface SuperuserActionResponse {
  status: SuperuserActionStatus;
  superuser_id: string | null;
  approval_request_id: string | null;
  detail: Record<string, unknown>;
}

export interface SuperuserApprovalEntry {
  approver_user_id?: string;
  approved_at?: string;
  [key: string]: unknown;
}

export interface SuperuserApprovalRequestSummary {
  id: string;
  action: string;
  detail: Record<string, unknown> | null;
  requested_by_id: string;
  approvals: SuperuserApprovalEntry[];
  status: 'pending' | 'applied' | 'rejected';
  created_at: string;
  executed_at: string | null;
}

export interface SuperuserApprovalRequestListResponse {
  items: SuperuserApprovalRequestSummary[];
  pending_count: number;
  min_approvals: number;
}

export interface SuperuserBreakGlassStatusResponse {
  active: boolean;
  started_at: string | null;
  expires_at: string | null;
  replacement_deadline_at: string | null;
  reason: string | null;
}

export interface SuperuserIpAllowlistResponse {
  superuser_id: string;
  allowed_ip_cidrs: string[];
  updated_at: string;
}

// Re-export ApiError so existing call sites can keep their
// ``import { ApiError } from '$lib/api/superusers'`` shorthand if any.
export { ApiError };

// ---------- Endpoints ----------

export const superuserApi = {
  /**
   * GET /web-api/v1/admin/superusers — list all rows + counts.
   */
  list: (): Promise<SuperuserListResponse> =>
    apiClient.get<SuperuserListResponse>(`${BASE}/superusers`),

  /**
   * POST /web-api/v1/admin/superusers — request promotion.
   * Returns `status: 'direct'` when active count < 3 (genesis), otherwise
   * `status: 'pending'` with a `approval_request_id`.
   */
  add: (payload: SuperuserAddRequest): Promise<SuperuserActionResponse> =>
    apiClient.post<SuperuserActionResponse>(
      `${BASE}/superusers`,
      payload,
      { headers: mutationHeaders() }
    ),

  /**
   * POST /web-api/v1/admin/superusers/{id}/revoke — open M-of-N revoke
   * ticket.  Always returns `status: 'pending'`; the DB trigger blocks the
   * apply step when revoking the last row (FR-111a).
   */
  revoke: (superuserId: string): Promise<SuperuserActionResponse> =>
    apiClient.post<SuperuserActionResponse>(
      `${BASE}/superusers/${superuserId}/revoke`,
      undefined,
      { headers: mutationHeaders() }
    ),

  /**
   * GET /web-api/v1/admin/superusers/approval-requests — pending M-of-N
   * tickets.  `status_filter` defaults to all on the backend.
   */
  listApprovalRequests: (
    statusFilter?: 'pending' | 'applied' | 'rejected',
  ): Promise<SuperuserApprovalRequestListResponse> => {
    const qs = statusFilter ? `?status_filter=${statusFilter}` : '';
    return apiClient.get<SuperuserApprovalRequestListResponse>(
      `${BASE}/superusers/approval-requests${qs}`,
    );
  },

  /**
   * POST /web-api/v1/admin/superusers/approval-requests/{id}/approve.
   */
  approve: (approvalRequestId: string): Promise<SuperuserActionResponse> =>
    apiClient.post<SuperuserActionResponse>(
      `${BASE}/superusers/approval-requests/${approvalRequestId}/approve`,
      undefined,
      { headers: mutationHeaders() },
    ),

  /**
   * POST /web-api/v1/admin/superusers/approval-requests/{id}/reject.
   * `reason` is required (1-2000 chars) per the contract.
   */
  reject: (
    approvalRequestId: string,
    reason: string,
  ): Promise<SuperuserActionResponse> =>
    apiClient.post<SuperuserActionResponse>(
      `${BASE}/superusers/approval-requests/${approvalRequestId}/reject`,
      { reason },
      { headers: mutationHeaders() },
    ),

  /**
   * POST /web-api/v1/admin/superusers/break-glass/enter — start a 72h
   * break-glass window.
   */
  enterBreakGlass: (
    reason: string,
  ): Promise<SuperuserBreakGlassStatusResponse> =>
    apiClient.post<SuperuserBreakGlassStatusResponse>(
      `${BASE}/superusers/break-glass/enter`,
      { reason },
      { headers: mutationHeaders() },
    ),

  /**
   * GET /web-api/v1/admin/superusers/break-glass/status.
   */
  breakGlassStatus: (): Promise<SuperuserBreakGlassStatusResponse> =>
    apiClient.get<SuperuserBreakGlassStatusResponse>(
      `${BASE}/superusers/break-glass/status`,
    ),

  /**
   * PATCH /web-api/v1/admin/superusers/{id}/ip-allowlist — replace the
   * canonicalised CIDR set.  Backend canonicalises and returns the
   * persisted value; UI should reload after success.
   */
  updateIpAllowlist: (
    superuserId: string,
    allowedIpCidrs: string[],
  ): Promise<SuperuserIpAllowlistResponse> =>
    apiClient.patch<SuperuserIpAllowlistResponse>(
      `${BASE}/superusers/${superuserId}/ip-allowlist`,
      { allowed_ip_cidrs: allowedIpCidrs },
      { headers: mutationHeaders() },
    ),
};
