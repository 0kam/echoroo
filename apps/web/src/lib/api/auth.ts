/**
 * Authentication API client (spec/009 PR B — BFF migration)
 *
 * Handles login, registration, and the spec/011 US4 step-up /
 * change-password ceremonies.
 *
 * Spec/009 PR B (2026-05-13): all callers now target the BFF
 * `/web-api/v1/auth/...` surface, which uses session cookies + CSRF
 * rather than the legacy v1 auth Bearer-JWT mount. The legacy mount is
 * retained for API-key clients but is no longer addressable from this
 * module. Mutating calls attach `X-CSRF-Token` from the `echoroo_csrf`
 * cookie via the same helper pattern used by `lib/api/projects.ts`.
 *
 * spec/011 zero-email deployment: the email-verification and emailed
 * password-reset flows were removed; their client helpers no longer
 * exist on this module.
 */
import type {
  User,
  LoginRequest,
  UserRegisterRequest,
  TokenResponse,
} from '$lib/types';
import { ApiError, apiClient } from './client';

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
 * spec/011 US4 — step-up ceremony response shapes (admin recovery flow).
 *
 * The two-step ceremony (`begin` → `complete`) issues a short-lived
 * scoped JWT that destructive admin endpoints accept via the
 * `X-Step-Up-Token` header. The flow is TOTP-only: WebAuthn-only users
 * receive a 409 `step_up_2fa_not_enrolled` from `begin`.
 */
export type StepUpScope = 'admin_recovery';

export interface StepUpBeginResponse {
  challenge_id: string;
  factors_required: string[];
}

export interface StepUpCompleteResponse {
  step_up_token: string;
  expires_at: string;
  scope_set: string[];
}

/**
 * spec/011 US4 — change-password response shape.
 *
 * The backend rotates the caller's `security_stamp` on a successful
 * change, which invalidates the OLD in-memory access token. It returns
 * a freshly-minted `access_token` (plus `expires_in`) so the client can
 * swap in the new credential before issuing any further session-gated
 * calls. Both fields are optional to stay tolerant of older backends
 * that only returned `{ message }`.
 */
export interface ChangePasswordResponse extends MessageResponse {
  access_token?: string;
  expires_in?: number;
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
  for (const key of ['error', 'error_code', 'code'] as const) {
    const value = obj[key];
    if (typeof value === 'string' && value.length > 0) return value;
  }
  // spec/011 step-up / change-password endpoints raise via
  // `HTTPException(detail={"error_code": "...", "message": "..."})`,
  // which FastAPI serialises as `{ "detail": { "error_code": ... } }`.
  // Mirror the central client so `err.code` is populated for the
  // nested-envelope shape too.
  const detail = obj.detail;
  if (typeof detail === 'object' && detail !== null) {
    const detailObj = detail as Record<string, unknown>;
    for (const key of ['error_code', 'error', 'code'] as const) {
      const value = detailObj[key];
      if (typeof value === 'string' && value.length > 0) return value;
    }
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

  // Attach the in-memory access token as a Bearer header WHEN one exists.
  // Session-gated BFF endpoints (step-up begin/complete, change-password)
  // are POST-auth and require `access_cookie OR Bearer`; there is no
  // access-token cookie, so the Bearer is the only credential that
  // satisfies the backend session middleware. Pre-auth flows (login,
  // 2FA setup/verify) run before any token exists, so `getAccessToken()`
  // returns null and nothing is attached — those flows are unchanged.
  // Mirrors the token + header construction in `client.ts` (`request()`).
  const accessToken = apiClient.getAccessToken();
  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`;
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
 * spec/011 US4 — begin a step-up ceremony for the given scope.
 *
 * Returns a `challenge_id` plus the factors the caller must satisfy
 * (`["password", "totp"]` for `admin_recovery`). A 409
 * `step_up_2fa_not_enrolled` indicates the operator has no TOTP factor
 * enrolled (WebAuthn-only) and therefore cannot complete this flow.
 */
export async function stepUpBegin(
  scope: StepUpScope
): Promise<StepUpBeginResponse> {
  return postAuth<StepUpBeginResponse>('/step-up/begin', { scope });
}

/**
 * spec/011 US4 — complete a step-up ceremony with the operator's
 * password + TOTP code.
 *
 * On success returns a short-lived `step_up_token` plus its
 * `expires_at` and granted `scope_set`. Any wrong / missing / expired
 * factor returns a uniform 401 `step_up_factor_invalid`; a stale
 * challenge therefore requires a fresh `stepUpBegin` before retrying.
 */
export async function stepUpComplete(
  challengeId: string,
  factors: { password: string; totpCode: string }
): Promise<StepUpCompleteResponse> {
  return postAuth<StepUpCompleteResponse>('/step-up/complete', {
    challenge_id: challengeId,
    factors: {
      password: factors.password,
      totp_code: factors.totpCode,
    },
  });
}

/**
 * spec/011 US4 — change the current user's password (self-service).
 *
 * Used by the forced-change screen after an admin reset. Errors:
 * 401 `current_password_invalid`, 400 `password_reused`,
 * 422 `password_policy_violation` (message carries the policy reason).
 */
export async function changePassword(
  currentPassword: string,
  newPassword: string
): Promise<ChangePasswordResponse> {
  return postAuth<ChangePasswordResponse>('/change-password', {
    current_password: currentPassword,
    new_password: newPassword,
  });
}
