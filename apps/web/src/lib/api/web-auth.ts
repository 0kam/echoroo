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

import { ApiError } from './client';

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
 * exists; `/password-reset/request` is anonymous; `/2fa/setup/totp` is the
 * pre-confirm "begin" call where the user has only an interim_token.
 */
const CSRF_EXEMPT_PATHS: ReadonlySet<string> = new Set([
  '/login',
  '/register',
  '/refresh',
  '/2fa/setup/totp',
  '/password-reset/request',
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

export async function requestPasswordReset(email: string): Promise<void> {
  await postJson<void>('/password-reset/request', { email });
}

export async function confirmPasswordReset(token: string, newPassword: string): Promise<void> {
  await postJson<void>('/password-reset/confirm', { token, new_password: newPassword });
}
