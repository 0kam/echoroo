/**
 * Superuser admin API client (Phase 15 / 006-permissions-redesign T955).
 *
 * Talks to the cookie-session protected `/web-api/v1/admin/superusers/*`
 * endpoints. All POST / PATCH calls attach `X-CSRF-Token` from the
 * `echoroo_csrf` cookie just like the rest of the web-auth router.
 *
 * Programmatic API keys are forbidden by the backend (FR-084): every call
 * is issued through the shared :data:`apiClient` so the request carries
 * BOTH the user's session cookie (``credentials: 'include'``) AND the
 * in-memory access token as ``Authorization: Bearer …``. The backend
 * auth router's session fast-path requires both pieces together — a
 * session cookie without a Bearer header 401s with
 * ``auth_required / Access token required`` (Phase 17 follow-up: was
 * regressed when this module shipped its own bare-fetch helper).
 */

import { ApiError, apiClient } from './client';
import { getActiveStepUpToken } from '$lib/utils/webauthnGating';

const BASE = '/web-api/v1/admin';
const CSRF_COOKIE_NAME = 'echoroo_csrf';
const STEP_UP_HEADER_NAME = 'X-Step-Up-Token';

// Phase 16 Batch 6g-3: which destructive admin paths require a
// ``X-Step-Up-Token`` header. The backend gate
// (``require_step_up_token``) is the source of truth — this list
// mirrors it so callers without a cached token can be redirected to
// the WebAuthn ceremony before issuing the request.
const STEP_UP_REQUIRED_METHODS = new Set(['POST', 'PATCH']);
function isStepUpRequiredPath(path: string): boolean {
  // Destructive endpoints all live under /superusers/* (excluding GETs
  // which are filtered by method). Listing endpoints stay on GET so the
  // method filter alone is sufficient.
  return path.startsWith('/superusers');
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

/**
 * Extract a structured `error` / `error_code` value from a JSON error body.
 *
 * Backend admin endpoints return either:
 *   - `{ "error": "ERR_LAST_SUPERUSER_PROTECTION", "message": "..." }`
 *   - `{ "detail": { "error": "...", "error_code": "...", "message": "..." } }`
 */
function extractErrorCode(errorData: unknown): string | null {
  if (typeof errorData !== 'object' || errorData === null) {
    return null;
  }
  const obj = errorData as Record<string, unknown>;
  for (const key of ['error', 'error_code', 'code']) {
    const value = obj[key];
    if (typeof value === 'string' && value.length > 0) return value;
  }
  // Nested under `detail`
  const detail = obj['detail'];
  if (typeof detail === 'object' && detail !== null) {
    const detailObj = detail as Record<string, unknown>;
    for (const key of ['error', 'error_code', 'code']) {
      const value = detailObj[key];
      if (typeof value === 'string' && value.length > 0) return value;
    }
  }
  return null;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const endpoint = `${BASE}${path}`;
  const method = (init.method ?? 'GET').toUpperCase();
  const headers: Record<string, string> = {};

  // Attach CSRF for state-changing verbs.
  if (method !== 'GET' && method !== 'HEAD') {
    const csrf = getCsrfToken();
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }

  // Phase 16 Batch 6g-3: attach a fresh step-up token for destructive
  // admin endpoints. Missing token → backend returns
  // 401 ``step_up_token_required`` so the UI can prompt for WebAuthn.
  if (STEP_UP_REQUIRED_METHODS.has(method) && isStepUpRequiredPath(path)) {
    const stepUp = getActiveStepUpToken();
    if (stepUp) headers[STEP_UP_HEADER_NAME] = stepUp;
  }

  // Merge caller-provided headers (they win over our defaults so callers
  // can override Content-Type for non-JSON payloads if ever needed).
  if (init.headers) {
    const provided = new Headers(init.headers);
    provided.forEach((value, key) => {
      headers[key] = value;
    });
  }

  // Delegate the actual transport to the shared :data:`apiClient`. It
  // attaches ``Authorization: Bearer <access_token>`` from its in-memory
  // store, sets ``Content-Type: application/json`` + ``credentials:
  // 'include'``, and on a 401 it transparently calls
  // ``/web-api/v1/auth/refresh`` and retries once with the rotated token.
  // Our custom CSRF + step-up headers ride along via ``options.headers``.
  try {
    return await apiClient.request<T>(endpoint, { ...init, headers });
  } catch (err) {
    // ``apiClient`` extracts ``code`` from ``{"error": "..."}`` and
    // ``{"code": "..."}`` envelopes but does not look inside a nested
    // ``detail`` object. Superuser endpoints sometimes return
    // ``{"detail": {"error_code": "..."}}`` — re-extract from the raw
    // body so UI branches like ``ERR_LAST_SUPERUSER_PROTECTION`` keep
    // matching after the rotation through ``apiClient``.
    if (err instanceof ApiError && !err.code && err.body !== null) {
      const richerCode = extractErrorCode(err.body);
      if (richerCode) {
        throw new ApiError(
          err.message,
          err.status,
          err.detail,
          richerCode,
          err.body,
        );
      }
    }
    throw err;
  }
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

// ---------- Endpoints ----------

export const superuserApi = {
  /**
   * GET /web-api/v1/admin/superusers — list all rows + counts.
   */
  list: (): Promise<SuperuserListResponse> => request('/superusers'),

  /**
   * POST /web-api/v1/admin/superusers — request promotion.
   * Returns `status: 'direct'` when active count < 3 (genesis), otherwise
   * `status: 'pending'` with a `approval_request_id`.
   */
  add: (payload: SuperuserAddRequest): Promise<SuperuserActionResponse> =>
    request('/superusers', { method: 'POST', body: JSON.stringify(payload) }),

  /**
   * POST /web-api/v1/admin/superusers/{id}/revoke — open M-of-N revoke
   * ticket.  Always returns `status: 'pending'`; the DB trigger blocks the
   * apply step when revoking the last row (FR-111a).
   */
  revoke: (superuserId: string): Promise<SuperuserActionResponse> =>
    request(`/superusers/${superuserId}/revoke`, { method: 'POST' }),

  /**
   * GET /web-api/v1/admin/superusers/approval-requests — pending M-of-N
   * tickets.  `status_filter` defaults to all on the backend.
   */
  listApprovalRequests: (
    statusFilter?: 'pending' | 'applied' | 'rejected',
  ): Promise<SuperuserApprovalRequestListResponse> => {
    const qs = statusFilter ? `?status_filter=${statusFilter}` : '';
    return request(`/superusers/approval-requests${qs}`);
  },

  /**
   * POST /web-api/v1/admin/superusers/approval-requests/{id}/approve.
   */
  approve: (approvalRequestId: string): Promise<SuperuserActionResponse> =>
    request(`/superusers/approval-requests/${approvalRequestId}/approve`, {
      method: 'POST',
    }),

  /**
   * POST /web-api/v1/admin/superusers/approval-requests/{id}/reject.
   * `reason` is required (1-2000 chars) per the contract.
   */
  reject: (
    approvalRequestId: string,
    reason: string,
  ): Promise<SuperuserActionResponse> =>
    request(`/superusers/approval-requests/${approvalRequestId}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  /**
   * POST /web-api/v1/admin/superusers/break-glass/enter — start a 72h
   * break-glass window.
   */
  enterBreakGlass: (
    reason: string,
  ): Promise<SuperuserBreakGlassStatusResponse> =>
    request('/superusers/break-glass/enter', {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  /**
   * GET /web-api/v1/admin/superusers/break-glass/status.
   */
  breakGlassStatus: (): Promise<SuperuserBreakGlassStatusResponse> =>
    request('/superusers/break-glass/status'),

  /**
   * PATCH /web-api/v1/admin/superusers/{id}/ip-allowlist — replace the
   * canonicalised CIDR set.  Backend canonicalises and returns the
   * persisted value; UI should reload after success.
   */
  updateIpAllowlist: (
    superuserId: string,
    allowedIpCidrs: string[],
  ): Promise<SuperuserIpAllowlistResponse> =>
    request(`/superusers/${superuserId}/ip-allowlist`, {
      method: 'PATCH',
      body: JSON.stringify({ allowed_ip_cidrs: allowedIpCidrs }),
    }),
};
