/**
 * Authentication API client (spec/009 PR B — BFF migration)
 *
 * Handles login, registration, password reset, and email verification.
 *
 * Spec/009 PR B (2026-05-13): all callers now target the BFF
 * `/web-api/v1/auth/...` surface, which uses session cookies + CSRF
 * rather than the legacy v1 auth Bearer-JWT mount. The legacy mount is
 * retained for API-key clients but is no longer addressable from this
 * module. Mutating calls attach `X-CSRF-Token` from the `echoroo_csrf`
 * cookie via the same helper pattern used by `lib/api/projects.ts`.
 *
 * NOTE on `verifyEmail` / `resendVerificationEmail`:
 *   - `/web-api/v1/auth/verify-email` and `/verify-email/resend` are
 *     anonymous pre-session BFF endpoints. Structured backend error
 *     codes are preserved in `ApiError.code` for safe UI branching.
 */
import type {
  User,
  LoginRequest,
  UserRegisterRequest,
  TokenResponse,
} from '$lib/types';
import { ApiError } from './client';

/**
 * Login response with user data
 */
export interface LoginResponse extends TokenResponse {
  user: User;
}

/**
 * Register response with user data
 */
export interface RegisterResponse {
  user: User;
  message: string;
}

/**
 * Generic success message response
 */
export interface MessageResponse {
  message: string;
}

/**
 * CSRF cookie name shared with the backend
 * (`settings.web_csrf_cookie_name`). Keep in sync with
 * `apps/web/src/lib/api/projects.ts` and `apps/web/src/lib/api/web-auth.ts`.
 */
const CSRF_COOKIE_NAME = 'echoroo_csrf';

/**
 * Pre-session BFF auth paths (relative to `/web-api/v1/auth`) where no
 * prior CSRF cookie can exist yet, so this client skips attaching
 * `X-CSRF-Token`. Mirrors `CSRF_EXEMPT_PATHS` in `web-auth.ts`.
 */
const CSRF_EXEMPT_PATHS: ReadonlySet<string> = new Set([
  '/login',
  '/register',
  '/refresh',
  '/password-reset/request',
  '/verify-email',
  '/verify-email/resend',
]);

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

function resolveBaseUrl(): string {
  if (typeof window !== 'undefined') {
    return '';
  }
  return import.meta.env.PUBLIC_API_URL || 'http://localhost:8002';
}

function extractErrorCode(errorData: unknown): string | null {
  if (typeof errorData !== 'object' || errorData === null) {
    return null;
  }
  const obj = errorData as Record<string, unknown>;
  if (typeof obj.error === 'string' && obj.error.length > 0) {
    return obj.error;
  }
  if (typeof obj.code === 'string' && obj.code.length > 0) {
    return obj.code;
  }
  return null;
}

/**
 * POST a JSON body to a `/web-api/v1/auth/...` endpoint. Handles cookie
 * session, CSRF double-submit, and the structured-error envelope used
 * across the BFF surface. The body is omitted on 204 No Content
 * responses (e.g. password reset confirm).
 */
async function postAuth<T>(path: string, body?: unknown): Promise<T> {
  const url = `${resolveBaseUrl()}/web-api/v1/auth${path}`;
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
    throw new ApiError(detail, response.status, detail, extractErrorCode(errorData), errorData);
  }

  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type');
  if (contentType?.includes('application/json')) {
    return (await response.json()) as T;
  }
  return {} as T;
}

/**
 * Login with email and password (BFF surface).
 *
 * NOTE: this thin wrapper is kept for type-compatibility only. The
 * production login flow (`routes/(auth)/login/+page.svelte`) calls
 * `lib/api/web-auth.ts::loginUser` directly because the BFF returns a
 * `{login_state, interim_token}` envelope rather than the legacy
 * `{user, access_token, refresh_token}` shape. Callers that import
 * this `login()` will receive the BFF body cast to `LoginResponse`,
 * which will be missing fields — use `loginUser` from `web-auth.ts`
 * instead.
 */
export async function login(data: LoginRequest): Promise<LoginResponse> {
  return postAuth<LoginResponse>('/login', data);
}

/**
 * Register a new user account (BFF surface).
 *
 * The production registration flow lives in
 * `routes/(auth)/register/+page.svelte` and uses `registerUser` from
 * `web-auth.ts`. This wrapper is preserved for type-import compatibility
 * but should be considered deprecated in favour of the typed
 * `RegisterRequest` / `RegisterResponse` exported from `web-auth.ts`.
 */
export async function register(data: UserRegisterRequest): Promise<RegisterResponse> {
  return postAuth<RegisterResponse>('/register', data);
}

/**
 * Logout the current user (BFF surface, idempotent).
 */
export async function logout(): Promise<void> {
  await postAuth<void>('/logout');
}

/**
 * Refresh the access token using the BFF refresh cookie.
 *
 * The BFF `refresh` endpoint sets cookies + returns a fresh access
 * token. The legacy v1 refresh endpoint reads a different cookie name
 * that the modern flow never writes and is intentionally unreachable
 * from here.
 */
export async function refreshToken(): Promise<TokenResponse> {
  return postAuth<TokenResponse>('/refresh');
}

/**
 * Request a password reset email (BFF surface, anonymous).
 */
export async function requestPasswordReset(email: string): Promise<MessageResponse> {
  return postAuth<MessageResponse>('/password-reset/request', { email });
}

/**
 * Confirm a password reset using the emailed token (BFF surface).
 *
 * The BFF schema uses `new_password` (the legacy v1 surface accepted
 * `password`); the conversion happens here so callers can keep using
 * the natural `password` argument name.
 */
export async function confirmPasswordReset(
  token: string,
  password: string
): Promise<MessageResponse> {
  return postAuth<MessageResponse>('/password-reset/confirm', {
    token,
    new_password: password,
  });
}

/**
 * Verify an email address with the token from the verification email.
 */
export async function verifyEmail(token: string): Promise<MessageResponse> {
  return postAuth<MessageResponse>('/verify-email', { token });
}

/**
 * Get the current authenticated user.
 *
 * Uses the BFF cookie + CSRF surface at ``/web-api/v1/users/me`` so
 * post-2FA browser sessions (which carry only the session cookie and
 * NOT a Bearer-JWT header) succeed instead of triggering the
 * auto-logout regression observed after spec/006's auth migration.
 *
 * Implementation moved here from PR #71's apiClient call; the BFF
 * `/me` path requires the same cookie-aware fetch shape as the rest
 * of this module.
 */
export async function getCurrentUser(): Promise<User> {
  const url = `${resolveBaseUrl()}/web-api/v1/users/me`;
  const headers: Record<string, string> = {};
  const csrfToken = getCsrfToken();
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  const response = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers,
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
    const detail =
      typeof errorData === 'object' && errorData !== null && 'detail' in errorData
        ? String((errorData as { detail: unknown }).detail)
        : 'Request failed';
    throw new ApiError(detail, response.status, detail);
  }
  return (await response.json()) as User;
}

/**
 * Resend the email verification mail to the current user.
 */
export async function resendVerificationEmail(): Promise<MessageResponse> {
  return postAuth<MessageResponse>('/verify-email/resend');
}
