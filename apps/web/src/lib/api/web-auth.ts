/**
 * First-party Web Auth API client (cookie-based sessions, CSRF, 2FA).
 *
 * Talks to the redesigned `/web-api/v1/auth/*` endpoints introduced in
 * Phase 4 of the permissions redesign (006-permissions-redesign).
 *
 * Unlike the legacy `/api/v1/auth/*` endpoints, these endpoints:
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
 * Internal helper: POST JSON to the web-auth endpoint and parse the response.
 * Throws an `ApiError` carrying the raw `Response` so callers can inspect
 * status codes (401, 423, 429) and headers (`Retry-After`).
 */
async function postJson<T>(path: string, body: unknown): Promise<{ data: T; response: Response }> {
  const url = `${resolveBaseUrl()}${BASE}${path}`;
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
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
    public readonly headers: Headers,
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

export type LoginState = '2fa_setup_required' | '2fa_required';

export interface LoginResponse {
  login_state: LoginState;
  interim_token: string;
}

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
}

export interface TotpChallengeResponse {
  access_token: string;
  expires_in: number;
}

export type TwoFactorMethod = 'totp' | 'backup_code';

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
): Promise<TotpConfirmResponse> {
  const { data } = await postJson<TotpConfirmResponse>('/2fa/setup/totp/confirm', {
    interim_token: interimToken,
    secret,
    totp_code: totpCode,
  });
  return data;
}

export async function challengeTwoFactor(
  interimToken: string,
  method: TwoFactorMethod,
  code: string,
): Promise<TotpChallengeResponse> {
  const { data } = await postJson<TotpChallengeResponse>('/2fa/challenge', {
    interim_token: interimToken,
    method,
    code,
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
