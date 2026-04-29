/**
 * Base API client for Echoroo backend
 */

/**
 * Custom error class for API errors.
 *
 * The optional `code` field carries the structured error envelope code that
 * the backend returns alongside `detail` / `message` (e.g.
 * `ERR_LICENSE_REQUIRED` for FR-085). UI callers should branch on `code`
 * for stable error identification rather than regex-matching `detail`.
 */
export class ApiError extends Error {
  /**
   * Structured error code from the backend envelope (e.g. `ERR_LICENSE_REQUIRED`).
   * `null` when the backend response does not include a `code`/`error` field
   * (legacy `{ "detail": "..." }`-only responses).
   */
  public code: string | null;

  /**
   * Raw decoded JSON body of the error response, when available.
   *
   * Phase 15 Batch 5b R2 (Codex Minor 1 fix): the IP allowlist editor
   * needs to inspect FastAPI 422 ``detail`` arrays
   * (``[{loc, msg, type}, ...]``) so it can render per-line CIDR
   * validation errors.  Storing the parsed body here keeps the typed
   * ``detail`` string unchanged for legacy callers while letting new
   * call sites opt into structured inspection.
   */
  public body: unknown;

  constructor(
    message: string,
    public status: number,
    public detail?: string,
    code?: string | null,
    body?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = code ?? null;
    this.body = body ?? null;
  }
}

/**
 * Extract the structured error envelope code from a JSON error body.
 *
 * Backend (Phase 7+) returns `{ "error": "ERR_LICENSE_REQUIRED", "message": "...", "detail": "..." }`
 * envelopes for structured failures. Older endpoints return just
 * `{ "detail": "..." }`. We accept either `error` or `code` as the source
 * field name to stay forward-compatible.
 */
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
 * Get API URL from environment or default.
 * In browser, use empty string so requests go through the vite proxy
 * (avoids CORS issues when accessing from different hosts).
 * On server-side, use the backend URL directly.
 */
function getApiUrl(): string {
  if (typeof window !== 'undefined') {
    // Browser: use relative URLs so requests go through vite proxy
    return '';
  }
  // Server-side: call backend directly
  return import.meta.env.PUBLIC_API_URL || 'http://localhost:8002';
}

/**
 * Public-readable path matchers — kept in lock-step with the backend
 * `auth_router.py` `public_path_prefix_allowlist` and
 * `public_path_nested_allowlist` (Phase 5 / FR-016).
 *
 * The frontend uses these to:
 *   1. Decide the credential profile per request. A signed-in caller keeps
 *      `credentials: 'include'` and the Bearer header so the backend can
 *      validate the session and serve member-aware variants. A Guest (no
 *      access token) goes anonymous: `credentials: 'omit'` and no Bearer.
 *   2. Provide a one-shot Guest fallback: if an authenticated public GET
 *      returns 401 (stale session, partial cookies, etc.), retry exactly
 *      once with `credentials: 'omit'` and no Bearer so the page still
 *      renders for the visitor.
 *   3. Skip the auto-refresh-on-401 retry for these paths. A 401 from a
 *      public path indicates a real authorization decision (e.g. Restricted
 *      project visibility), not an expired token, so refreshing wastes a
 *      round-trip and can spiral into a refresh loop when the refresh
 *      cookie itself is also expired.
 *
 * Patterns:
 *   - `/web-api/v1/projects` (list)
 *   - `/web-api/v1/projects/{id}` (detail)
 *   - `/web-api/v1/projects/{id}/recordings` (Phase 5 nested allowlist)
 *
 * Anything else under `/web-api/v1/projects/{id}/...` (members, trusted
 * users, etc.) is intentionally NOT matched here — those endpoints are
 * cookie + CSRF protected and should keep the Authorization-free,
 * credentials-include behaviour from `callWebApi` in `projects.ts`.
 */
const PUBLIC_PATH_PATTERNS: readonly RegExp[] = [
  // /web-api/v1/projects, /web-api/v1/projects/, /web-api/v1/projects/{id},
  // /web-api/v1/projects/{id}/, plus optional trailing query is stripped
  // before matching by `stripQuery`.
  /^\/web-api\/v1\/projects\/?$/,
  /^\/web-api\/v1\/projects\/[^/]+\/?$/,
  /^\/web-api\/v1\/projects\/[^/]+\/recordings\/?$/,
];

function stripQuery(endpoint: string): string {
  const qIdx = endpoint.indexOf('?');
  return qIdx === -1 ? endpoint : endpoint.slice(0, qIdx);
}

/**
 * Return ``true`` when ``endpoint`` is a Guest-readable web-API path that
 * MUST be issued without an Authorization header so an expired JWT cannot
 * cause the backend auth router to reject the request.
 *
 * Only GET requests qualify; mutating verbs are never on the public
 * allowlist (the backend allowlist also restricts to GET).
 */
export function isPublicReadablePath(
  endpoint: string,
  method: string = 'GET'
): boolean {
  if (method.toUpperCase() !== 'GET') return false;
  const path = stripQuery(endpoint);
  return PUBLIC_PATH_PATTERNS.some((pattern) => pattern.test(path));
}

export class ApiClient {
  private baseUrl: string;
  private accessToken: string | null = null;
  private refreshPromise: Promise<void> | null = null;
  /**
   * Latch that disables automatic refresh after the refresh cookie itself
   * expired. Prevents a tight loop where every public-page background
   * fetch (TanStack Query refetch on focus, etc.) re-attempts
   * `/api/v1/auth/refresh` and gets 401 in response.
   *
   * Cleared by ``setAccessToken`` so a successful re-login (or any path
   * that explicitly stamps a fresh access token) re-arms the auto-refresh
   * machinery.
   */
  private refreshDisabledUntilLogin: boolean = false;

  constructor(baseUrl?: string) {
    this.baseUrl = baseUrl || getApiUrl();
  }

  /**
   * Set access token for authenticated requests
   */
  setAccessToken(token: string | null) {
    this.accessToken = token;
    if (token) {
      // A fresh token implies a successful login / refresh — re-arm the
      // auto-refresh latch so subsequent 401s on private paths resume the
      // normal refresh-and-retry flow.
      this.refreshDisabledUntilLogin = false;
    }
  }

  /**
   * Get current access token
   */
  getAccessToken(): string | null {
    return this.accessToken;
  }

  /**
   * Public method to trigger a token refresh.
   * Deduplicates concurrent refresh attempts via the shared refreshPromise.
   */
  async refreshToken(): Promise<void> {
    return this.refreshAccessToken();
  }

  /**
   * Callback invoked when token refresh fails with a 401.
   * Set externally by the auth store to handle session cleanup and redirect.
   */
  onRefreshFailed: (() => void) | null = null;

  /**
   * Refresh access token using refresh token from cookie.
   *
   * Targets the first-party web-auth endpoint
   * `/web-api/v1/auth/refresh`. The modern login flow sets the
   * `echoroo_refresh` HttpOnly cookie on `Path=/web-api/v1/auth/refresh`
   * (see `_set_session_cookies` in the backend), and only that endpoint
   * recognises it. The legacy `/api/v1/auth/refresh` route reads a
   * different cookie name (`refresh_token`) that the modern flow never
   * sets, so calling it always returned 401 and produced the
   * re-login → /users/me 401 → refresh 401 → onRefreshFailed → logout
   * loop observed in Phase 11 browser smoke tests.
   *
   * When the refresh cookie itself is expired (server returns 401), we
   * latch ``refreshDisabledUntilLogin`` so that subsequent 401s do NOT
   * trigger another refresh attempt. This breaks the loop seen on the
   * Guest-public pages where a stale auth cookie + private background
   * fetches caused dozens of refresh calls per page. The latch is
   * cleared by ``setAccessToken`` on a successful login.
   */
  private async refreshAccessToken(): Promise<void> {
    // If a previous refresh attempt failed with 401 we must NOT spin a
    // new refresh — every subsequent call would also fail. Throw the
    // canonical failure marker so the caller's `catch` branch runs.
    if (this.refreshDisabledUntilLogin) {
      throw new ApiError('Token refresh disabled until next login', 401);
    }

    // If already refreshing, wait for that promise
    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    this.refreshPromise = (async () => {
      try {
        const response = await fetch(`${this.baseUrl}/web-api/v1/auth/refresh`, {
          method: 'POST',
          credentials: 'include', // Send refresh token cookie
          headers: {
            'Content-Type': 'application/json',
          },
          signal: AbortSignal.timeout(10000),
        });

        if (!response.ok) {
          if (response.status === 401) {
            // Refresh token is invalid or expired - notify the auth layer
            // and latch so we don't keep hammering the endpoint.
            this.accessToken = null;
            this.refreshDisabledUntilLogin = true;
            if (this.onRefreshFailed) {
              this.onRefreshFailed();
            }
          }
          throw new ApiError('Token refresh failed', response.status);
        }

        const data = await response.json();
        this.accessToken = data.access_token;
        // Successful refresh — re-arm in case a previous attempt latched.
        this.refreshDisabledUntilLogin = false;
      } finally {
        this.refreshPromise = null;
      }
    })();

    return this.refreshPromise;
  }

  async request<T>(
    endpoint: string,
    options: RequestInit = {},
    retry = true
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const method = (options.method ?? 'GET').toUpperCase();
    const isPublic = isPublicReadablePath(endpoint, method);

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    // Path-aware Authorization (Phase 4-5-6 carry-over Round 2 致命):
    //   - Private paths: attach `Bearer <accessToken>` when present.
    //   - Public-readable paths AND signed-in user (accessToken present):
    //     attach Bearer too. The backend auth router's session fast-path
    //     specifically requires `session_cookie + access_token` together;
    //     sending the session cookie WITHOUT a Bearer would 401 because
    //     the public-allowlist branch falls through to `_authenticate_session`
    //     and that branch demands both pieces. With the Bearer attached,
    //     authenticated users keep full access on public pages.
    //   - Public-readable paths AND Guest (no accessToken): no Bearer.
    //     Combined with `credentials: 'omit'` below the request becomes
    //     fully anonymous and the auth router's Guest fast-path admits it.
    if (this.accessToken) {
      headers['Authorization'] = `Bearer ${this.accessToken}`;
    }

    // Merge with provided headers
    if (options.headers) {
      const providedHeaders = new Headers(options.headers);
      providedHeaders.forEach((value, key) => {
        headers[key] = value;
      });
    }

    // For Guest requests on public-readable paths we deliberately strip
    // cookies (`credentials: 'omit'`) so a stale `echoroo_session` cookie
    // — left over after a prior session was revoked / expired — cannot
    // force the backend into the session-required branch and 401 the
    // call. Authenticated visitors keep `credentials: 'include'` so their
    // session cookie travels alongside the Bearer header.
    const useGuestCredentials = isPublic && !this.accessToken;
    const config: RequestInit = {
      ...options,
      credentials: useGuestCredentials ? 'omit' : 'include',
      headers,
    };

    let response = await fetch(url, config);

    // Phase 4-5-6 carry-over Round 2 致命 fallback: when an authenticated
    // user (or one carrying a stale session cookie) hits a public-readable
    // path and the backend rejects the session-required branch with 401,
    // retry ONCE as a true Guest (no Bearer, no cookies). This guarantees
    // public pages keep rendering for any caller, even if their session
    // state is broken/expired in subtle ways.
    if (response.status === 401 && retry && isPublic && !useGuestCredentials) {
      const guestHeaders: Record<string, string> = {
        'Content-Type': 'application/json',
      };
      if (options.headers) {
        const providedHeaders = new Headers(options.headers);
        providedHeaders.forEach((value, key) => {
          guestHeaders[key] = value;
        });
      }
      // Drop any Authorization header that may have been merged in via
      // the provided headers — this retry must be fully anonymous. The
      // `Headers` constructor lower-cases keys when iterating, so strip
      // both casings to be safe.
      delete guestHeaders['Authorization'];
      delete guestHeaders['authorization'];
      response = await fetch(url, {
        ...options,
        credentials: 'omit',
        headers: guestHeaders,
      });
    }

    // Handle 401 Unauthorized - try to refresh token.
    //
    // Public-readable paths short-circuit this branch: a 401 from
    // `/web-api/v1/projects/...` is an authorization decision (e.g.
    // Restricted project), not an expired access token, so refreshing
    // would only trigger a useless `/api/v1/auth/refresh` round-trip and
    // potentially a refresh-loop when the refresh cookie itself is also
    // expired.
    if (response.status === 401 && retry && !isPublic) {
      try {
        await this.refreshAccessToken();

        // Retry request with new token
        const retryHeaders: Record<string, string> = {
          'Content-Type': 'application/json',
        };

        if (this.accessToken) {
          retryHeaders['Authorization'] = `Bearer ${this.accessToken}`;
        }

        // Merge with provided headers
        if (options.headers) {
          const providedHeaders = new Headers(options.headers);
          providedHeaders.forEach((value, key) => {
            retryHeaders[key] = value;
          });
        }

        response = await fetch(url, {
          ...config,
          headers: retryHeaders,
        });
      } catch {
        // Refresh failed, throw original 401 error
        const errorData = await response.json().catch(() => ({
          detail: 'Unauthorized',
        }));
        throw new ApiError(
          errorData.detail || errorData.message || 'Unauthorized',
          401,
          errorData.detail || errorData.message,
          extractErrorCode(errorData)
        );
      }
    }

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({
        detail: 'An error occurred',
      }));
      throw new ApiError(
        errorData.detail || errorData.message || 'Request failed',
        response.status,
        errorData.detail || errorData.message,
        extractErrorCode(errorData)
      );
    }

    // Handle empty responses (e.g., 204 No Content)
    if (response.status === 204) {
      return undefined as T;
    }

    const contentType = response.headers.get('content-type');
    if (contentType?.includes('application/json')) {
      return response.json();
    }

    return {} as T;
  }

  async get<T>(endpoint: string, options?: RequestInit): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'GET' });
  }

  async post<T>(
    endpoint: string,
    data?: unknown,
    options?: RequestInit
  ): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async patch<T>(
    endpoint: string,
    data?: unknown,
    options?: RequestInit
  ): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async put<T>(
    endpoint: string,
    data?: unknown,
    options?: RequestInit
  ): Promise<T> {
    return this.request<T>(endpoint, {
      ...options,
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async delete<T>(endpoint: string, options?: RequestInit): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'DELETE' });
  }

  /**
   * Send a request and return the raw Response without automatic JSON parsing.
   * Useful for file downloads (blob/arrayBuffer) or multipart/form-data uploads
   * where automatic Content-Type injection must be avoided.
   * Handles 401 token refresh and retry automatically.
   */
  async requestRaw(
    endpoint: string,
    options: RequestInit = {},
    retry = true
  ): Promise<Response> {
    const url = `${this.baseUrl}${endpoint}`;
    const method = (options.method ?? 'GET').toUpperCase();
    const isPublic = isPublicReadablePath(endpoint, method);

    const headers: Record<string, string> = {};

    // Match `request()` semantics (Round 2 致命): authenticated callers
    // attach Bearer on public paths too so the session-required branch
    // succeeds; Guest callers omit cookies+Bearer to take the Guest
    // fast-path.
    if (this.accessToken) {
      headers['Authorization'] = `Bearer ${this.accessToken}`;
    }

    // Merge with provided headers (allows caller to set Content-Type or omit it)
    if (options.headers) {
      const providedHeaders = new Headers(options.headers);
      providedHeaders.forEach((value, key) => {
        headers[key] = value;
      });
    }

    const useGuestCredentials = isPublic && !this.accessToken;
    const config: RequestInit = {
      ...options,
      credentials: useGuestCredentials ? 'omit' : 'include',
      headers,
    };

    let response = await fetch(url, config);

    // Public-path Guest fallback retry: if an authenticated request to a
    // public path 401s, retry once as anonymous Guest.
    if (response.status === 401 && retry && isPublic && !useGuestCredentials) {
      const guestHeaders: Record<string, string> = {};
      if (options.headers) {
        const providedHeaders = new Headers(options.headers);
        providedHeaders.forEach((value, key) => {
          guestHeaders[key] = value;
        });
      }
      // Strip both casings — the `Headers` iterator lower-cases keys.
      delete guestHeaders['Authorization'];
      delete guestHeaders['authorization'];
      response = await fetch(url, {
        ...options,
        credentials: 'omit',
        headers: guestHeaders,
      });
    }

    if (response.status === 401 && retry && !isPublic) {
      try {
        await this.refreshAccessToken();

        const retryHeaders: Record<string, string> = {};
        if (this.accessToken) {
          retryHeaders['Authorization'] = `Bearer ${this.accessToken}`;
        }
        if (options.headers) {
          const providedHeaders = new Headers(options.headers);
          providedHeaders.forEach((value, key) => {
            retryHeaders[key] = value;
          });
        }

        response = await fetch(url, {
          ...config,
          headers: retryHeaders,
        });
      } catch {
        // Refresh failed, return original 401 response
      }
    }

    return response;
  }

  /**
   * Fetch a raw binary resource (e.g., image, audio) with authentication.
   * Returns the raw Response so callers can convert to blob for use with
   * URL.createObjectURL(). Handles token refresh on 401.
   */
  async fetchRaw(endpoint: string, retry = true): Promise<Response> {
    const url = `${this.baseUrl}${endpoint}`;
    const isPublic = isPublicReadablePath(endpoint, 'GET');

    const headers: Record<string, string> = {};
    if (this.accessToken) {
      headers['Authorization'] = `Bearer ${this.accessToken}`;
    }

    const useGuestCredentials = isPublic && !this.accessToken;
    let response = await fetch(url, {
      method: 'GET',
      credentials: useGuestCredentials ? 'omit' : 'include',
      headers,
    });

    // Public-path Guest fallback retry: see `request()` for full rationale.
    if (response.status === 401 && retry && isPublic && !useGuestCredentials) {
      response = await fetch(url, {
        method: 'GET',
        credentials: 'omit',
        headers: {},
      });
    }

    if (response.status === 401 && retry && !isPublic) {
      try {
        await this.refreshAccessToken();

        const retryHeaders: Record<string, string> = {};
        if (this.accessToken) {
          retryHeaders['Authorization'] = `Bearer ${this.accessToken}`;
        }

        response = await fetch(url, {
          method: 'GET',
          credentials: 'include',
          headers: retryHeaders,
        });
      } catch {
        // Refresh failed, return the 401 response
      }
    }

    return response;
  }
}

// Export singleton instance
export const apiClient = new ApiClient();
