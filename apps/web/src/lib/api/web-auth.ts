/**
 * First-party Web Auth API client (cookie-based sessions, CSRF, 2FA).
 *
 * Talks to the redesigned `/web-api/v1/auth/*` endpoints introduced in
 * Phase 4 of the permissions redesign (006-permissions-redesign).
 *
 * Unlike the legacy v1 auth endpoints, these endpoints:
 * - Do NOT log the user in on register; 2FA setup is enforced on first login.
 * - Issue an `interim_token` (JWT) on login that must be exchanged via either
 *   `/2fa/setup/totp` (first-time setup) or `/2fa/challenge` (existing 2FA).
 * - Set HttpOnly cookies on successful 2FA confirm/challenge.
 *
 * Use this client for all new auth flows; the legacy `auth.ts` is retained
 * only to keep older pages compiling until they are migrated.
 */

import { ApiError, apiClient } from './client';

const BASE = '/web-api/v1/auth';

/**
 * CSRF cookie name. Must match `settings.web_csrf_cookie_name` in the
 * backend (`apps/api/echoroo/core/settings.py`). The cookie is set with
 * `httponly=False` so this client can read it from `document.cookie`.
 */
const CSRF_COOKIE_NAME = 'echoroo_csrf';

/**
 * Pre-session paths (relative to `BASE`) where no prior CSRF cookie can
 * exist yet, so this client SKIPS attaching `X-CSRF-Token` even if a
 * stale cookie happened to leak in from another flow. The backend
 * exempts a slightly larger set in `PUBLIC_AUTH_PATHS`
 * (`apps/api/echoroo/core/auth_paths.py`); for the *interim_token*
 * confirm/challenge endpoints we still attach the header opportunistically
 * (when the cookie is present) — the backend tolerates it and this keeps
 * our defence-in-depth posture honest.
 *
 * Strictly: `/login` / `/register` / `/refresh` happen before any session
 * exists; `/2fa/setup/totp` is the pre-confirm "begin" call where the user
 * has only an interim_token.
 */
const CSRF_EXEMPT_PATHS: ReadonlySet<string> = new Set([
  '/login',
  '/register',
  '/refresh',
  '/2fa/setup/totp',
]);

/**
 * Resolve the API base URL the same way the shared `apiClient` does:
 * relative URLs in the browser (so requests pass through the Vite proxy)
 * and an explicit URL on the server.
 */
function resolveBaseUrl(): string {
  if (typeof window !== 'undefined') {
    return '';
  }
  return import.meta.env.PUBLIC_API_URL || 'http://localhost:8002';
}

/**
 * Read the CSRF token from `document.cookie`. Returns `null` if the
 * cookie is absent (e.g. pre-session flows) or the helper is invoked on
 * the server (no `document`).
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
 * Internal helper: POST JSON to the web-auth endpoint and parse the response.
 * Throws an `ApiError` carrying the raw `Response` so callers can inspect
 * status codes (401, 423, 429) and headers (`Retry-After`).
 *
 * Automatically attaches `X-CSRF-Token` for state-changing endpoints that
 * are NOT in the backend's CSRF-exempt allowlist (`PUBLIC_AUTH_PATHS`).
 */
async function postJson<T>(path: string, body: unknown): Promise<{ data: T; response: Response }> {
  const url = `${resolveBaseUrl()}${BASE}${path}`;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const csrfToken = getCsrfToken();
  if (csrfToken && !CSRF_EXEMPT_PATHS.has(path)) {
    headers['X-CSRF-Token'] = csrfToken;
  }
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers,
    body: JSON.stringify(body ?? {}),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
    const detail =
      typeof errorData === 'object' && errorData !== null && 'detail' in errorData
        ? String((errorData as { detail: unknown }).detail)
        : 'Request failed';
    throw new WebAuthError(detail, response.status, response.headers);
  }

  if (response.status === 204) {
    return { data: undefined as T, response };
  }
  const contentType = response.headers.get('content-type');
  if (contentType?.includes('application/json')) {
    const data = (await response.json()) as T;
    return { data, response };
  }
  return { data: {} as T, response };
}

/**
 * `ApiError` subclass that preserves response headers so callers can read
 * `Retry-After` for rate-limit / lockout flows.
 */
export class WebAuthError extends ApiError {
  constructor(
    message: string,
    status: number,
    public readonly headers: Headers
  ) {
    super(message, status, message);
    this.name = 'WebAuthError';
  }

  /**
   * Parse `Retry-After` header into seconds. Returns `null` if missing/invalid.
   */
  retryAfterSeconds(): number | null {
    const raw = this.headers.get('Retry-After');
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? Math.ceil(n) : null;
  }
}

// ---------- Request / response types ----------

export interface RegisterRequest {
  email: string;
  password: string;
  display_name?: string;
  timezone?: string;
}

export interface RegisterResponse {
  user_id: string;
  email: string;
  two_factor_setup_required: true;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export type LoginState = '2fa_setup_required' | '2fa_required' | 'complete';

interface LoginInterimResponse {
  login_state: Exclude<LoginState, 'complete'>;
  interim_token: string;
}

interface LoginCompleteResponse {
  login_state: 'complete';
  access_token: string;
  expires_in: number;
  trusted_device_used?: boolean;
}

export type LoginResponse = LoginInterimResponse | LoginCompleteResponse;

export interface TotpSetupResponse {
  secret: string;
  provisioning_uri: string;
  issuer: string;
  account_name: string;
  next_interim_token: string;
}

export interface TotpConfirmResponse {
  backup_codes: string[];
  access_token: string;
  expires_in: number;
  trusted_device_created?: boolean;
}

export interface TotpChallengeResponse {
  access_token: string;
  expires_in: number;
  trusted_device_created?: boolean;
}

export type TwoFactorMethod = 'totp' | 'backup_code';

export interface TrustDeviceOptions {
  trustDevice?: boolean;
  deviceLabel?: string;
}

// ---------- Endpoints ----------

export async function registerUser(req: RegisterRequest): Promise<RegisterResponse> {
  const { data } = await postJson<RegisterResponse>('/register', req);
  return data;
}

export async function loginUser(req: LoginRequest): Promise<LoginResponse> {
  const { data } = await postJson<LoginResponse>('/login', req);
  return data;
}

export async function setupTotp(interimToken: string): Promise<TotpSetupResponse> {
  const { data } = await postJson<TotpSetupResponse>('/2fa/setup/totp', {
    interim_token: interimToken,
  });
  return data;
}

export async function confirmTotpSetup(
  interimToken: string,
  secret: string,
  totpCode: string,
  options: TrustDeviceOptions = {}
): Promise<TotpConfirmResponse> {
  const { data } = await postJson<TotpConfirmResponse>('/2fa/setup/totp/confirm', {
    interim_token: interimToken,
    secret,
    totp_code: totpCode,
    trust_device: options.trustDevice,
    device_label: options.deviceLabel,
  });
  return data;
}

export async function challengeTwoFactor(
  interimToken: string,
  method: TwoFactorMethod,
  code: string,
  options: TrustDeviceOptions = {}
): Promise<TotpChallengeResponse> {
  const { data } = await postJson<TotpChallengeResponse>('/2fa/challenge', {
    interim_token: interimToken,
    method,
    code,
    trust_device: options.trustDevice,
    device_label: options.deviceLabel,
  });
  return data;
}

export async function logoutUser(): Promise<void> {
  await postJson<void>('/logout', {});
}

// ---------- Public invitation flow (spec/011 US2, T223) ----------

/**
 * `GET /web-api/v1/auth/invitations/{token}` 200 body (FR-011-105).
 *
 * `bound_email` is `null` when an authenticated caller's own email does NOT
 * match the invitation (anti-enumeration — never leak the invitee identity
 * to a wrong-account session). It is always present for the anonymous
 * signup branch.
 */
export interface InvitationContextResponse {
  project_name: string;
  /** Member-kind role; `null` for trusted-overlay invitations. */
  role: 'viewer' | 'member' | 'admin' | null;
  /** `'member'` or `'trusted'`. */
  kind: string;
  bound_email: string | null;
  /** ISO-8601 expiry timestamp. */
  expires_at: string;
  is_bootstrap: boolean;
  is_logged_in: boolean;
  authenticated_email_matches_bound: boolean;
}

/** New-user signup branch payload (FR-011-106 step 1a). */
export interface InvitationAcceptNewUserPayload {
  /** MUST canonicalize-equal `bound_email`; mismatch collapses to a 404. */
  email: string;
  /** Min 12 chars; backend additionally rejects HIBP-compromised passwords. */
  password: string;
  totp_enrollment: {
    /** Client-generated base32 secret (the field name is "signed" for forward-compat). */
    totp_secret_signed: string;
    /** Exactly 6 digits. */
    totp_initial_code: string;
  };
}

/** Existing-user accept branch payload (FR-011-106 step 1b). */
export interface InvitationAcceptExistingPayload {
  accept: true;
}

/**
 * `POST /web-api/v1/auth/invitations/{token}/accept` 201 body (FR-011-106).
 *
 * NOTE: the body carries NO `access_token` / `user`. For the new-user
 * branch the backend establishes the session SERVER-SIDE (sets HttpOnly
 * cookies on the 201 response), so the caller must hydrate the in-memory
 * session via `authStore.initialize()` rather than reading a token here.
 */
export interface InvitationAcceptResponse {
  project_id: string;
  role: 'viewer' | 'member' | 'admin' | null;
  kind: string;
  ownership_transferred: boolean;
  membership_created: boolean;
}

/**
 * Build a `WebAuthError` from a non-OK response, preserving the structured
 * envelope code (`detail.error`) and raw body so callers can branch on
 * `err.code` (e.g. `ERR_ALREADY_MEMBER`) and `err.status`.
 */
async function webAuthErrorFromResponse(response: Response): Promise<WebAuthError> {
  const data = (await response.json().catch(() => null)) as
    | { detail?: unknown; error?: unknown; message?: unknown }
    | null;
  let message = 'Request failed';
  let code: string | null = null;
  if (data && typeof data === 'object') {
    const detail = data.detail;
    if (typeof detail === 'string') {
      message = detail;
    } else if (detail && typeof detail === 'object') {
      const d = detail as Record<string, unknown>;
      if (typeof d.message === 'string') message = d.message;
      if (typeof d.error === 'string') code = d.error;
    }
    if (!code && typeof data.error === 'string') code = data.error;
    if (typeof data.message === 'string' && message === 'Request failed') {
      message = data.message;
    }
  }
  const err = new WebAuthError(message, response.status, response.headers);
  err.code = code;
  err.body = data;
  return err;
}

/**
 * `GET /web-api/v1/auth/invitations/{token}` — OPTIONAL-auth resolver
 * (token-in-path). The backend resolver reads the optional current user to
 * set `is_logged_in` / `authenticated_email_matches_bound`. Because the BFF
 * `/web-api/v1/*` mount authenticates the session via the in-memory
 * `Authorization: Bearer <access-token>` (there is no access-token cookie),
 * we MUST attach the Bearer WHEN a logged-in user opens the link, otherwise
 * the resolver returns 401 `auth_required` instead of the existing-user
 * accept context. Conversely, a logged-OUT new-user visitor has NO token —
 * we attach NO Authorization header so the backend treats the request as
 * anonymous and returns the signup branch. Cookies are always sent.
 *
 * Mirrors the conditional-Bearer construction in `auth.ts` (`postAuth`) and
 * `client.ts` (`request()`).
 */
export async function resolveInvitation(
  token: string
): Promise<InvitationContextResponse> {
  const url = `${resolveBaseUrl()}${BASE}/invitations/${encodeURIComponent(token)}`;
  const headers: Record<string, string> = {};
  // Conditional Bearer: attach the in-memory access token only when a
  // logged-in session exists. A logged-out new-user visitor has no token
  // (`getAccessToken()` returns null) → no header → backend signup branch.
  const accessToken = apiClient.getAccessToken();
  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }
  const response = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers,
  });
  if (!response.ok) {
    throw await webAuthErrorFromResponse(response);
  }
  return (await response.json()) as InvitationContextResponse;
}

/**
 * `POST /web-api/v1/auth/invitations/{token}/accept` — accept an invitation.
 *
 * The payload shape branches on the caller's auth state: anonymous callers
 * send the new-user signup payload; logged-in callers send `{ accept: true }`.
 * Attaches the CSRF token (when a cookie is present) and sends cookies, the
 * same way `postJson` does, but parses the structured error envelope so the
 * caller can branch on `err.code` (e.g. `ERR_ALREADY_MEMBER`). For the
 * new-user branch the backend sets session cookies on the 201 response — the
 * caller must then hydrate via `authStore.initialize()`.
 *
 * Like `resolveInvitation`, the accept endpoint is OPTIONAL-auth: the
 * existing-user `{ accept: true }` branch MUST carry the in-memory
 * `Authorization: Bearer <access-token>` so the BFF recognizes the session
 * and takes the existing-user path; the logged-OUT new-user branch has no
 * token and sends NO Authorization header so the backend creates the account
 * via the signup payload.
 */
export async function acceptInvitation(
  token: string,
  payload: InvitationAcceptNewUserPayload | InvitationAcceptExistingPayload
): Promise<InvitationAcceptResponse> {
  const path = `/invitations/${encodeURIComponent(token)}/accept`;
  const url = `${resolveBaseUrl()}${BASE}${path}`;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const csrfToken = getCsrfToken();
  if (csrfToken && !CSRF_EXEMPT_PATHS.has(path)) {
    headers['X-CSRF-Token'] = csrfToken;
  }
  // Conditional Bearer (mirrors `auth.ts` `postAuth` / `client.ts`): the
  // existing-user accept branch is issued from a logged-in session, so the
  // Bearer is the only credential the BFF session middleware accepts (no
  // access-token cookie exists). The logged-out new-user branch has no token
  // → no header → backend signup path stays anonymous.
  const accessToken = apiClient.getAccessToken();
  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers,
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await webAuthErrorFromResponse(response);
  }
  return (await response.json()) as InvitationAcceptResponse;
}
