/**
 * Authentication store using Svelte 5 runes
 */

import type { User } from '$lib/types';
import { apiClient } from '$lib/api/client';
import { logoutUser as webLogoutUser } from '$lib/api/web-auth';
import { goto } from '$app/navigation';
import { localizeHref } from '$lib/paraglide/runtime';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

/**
 * Round 2 Major fix helper — fire-and-forget POST to the CSRF-exempt
 * `/web-api/v1/auth/logout` endpoint to clear the HttpOnly
 * `echoroo_logged_in` marker cookie (and any remaining session/CSRF
 * cookies). Used from silent fail-safe paths (`initialize({silent})` 401)
 * and from the global `onRefreshFailed` callback so a stale marker cookie
 * never persists past a known auth failure.
 *
 * Errors are swallowed: the goal is best-effort cookie eviction; the
 * endpoint is idempotent (always returns 204) so a transient network
 * failure simply means the next page load will retry naturally.
 */
async function clearMarkerCookieBestEffort(): Promise<void> {
  if (typeof window === 'undefined') return;
  try {
    await apiClient.requestRaw(
      '/web-api/v1/auth/logout',
      { method: 'POST' },
      false, // do not retry on 401 — logout is idempotent and CSRF-exempt
    );
  } catch {
    // Best-effort only — see docstring.
  }
}

interface LoginCredentials {
  email: string;
  password: string;
}

interface LoginResponse {
  access_token: string;
  user: User;
}

function createAuthStore() {
  const state = $state<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: true,
  });

  return {
    get user() {
      return state.user;
    },
    get isAuthenticated() {
      return state.isAuthenticated;
    },
    get isLoading() {
      return state.isLoading;
    },

    /**
     * Set user and update authentication state
     */
    setUser(user: User | null) {
      state.user = user;
      state.isAuthenticated = user !== null;
      state.isLoading = false;
    },

    /**
     * Clear user and reset authentication state
     */
    clearUser() {
      state.user = null;
      state.isAuthenticated = false;
      state.isLoading = false;
    },

    /**
     * Set loading state
     */
    setLoading(loading: boolean) {
      state.isLoading = loading;
    },

    /**
     * Initialize auth state by checking current session.
     *
     * On page reload the in-memory access token is lost, so we proactively
     * attempt a token refresh before calling /users/me. This prevents child
     * routes from receiving 401 errors while the token is being restored.
     *
     * Behaviour modes (Phase 4-5-6 carry-over fix #3):
     *   - `silent: false` (default) — when refresh / `/users/me` fails with
     *     401 we redirect to `/login`. Used by auth-required routes.
     *   - `silent: true` — fail-safe: clear auth state to `{user: null,
     *     isAuthenticated: false}` but DO NOT trigger any client-side
     *     navigation. Used by `(public)` and `(auth)` route groups so a
     *     stale `echoroo_logged_in` marker cookie + invalid refresh
     *     cookie does not bounce a Guest browsing `/en/explore/...` away
     *     to `/login` (which `hooks.server.ts` then re-redirects to
     *     `/dashboard` via the `isAuthRoute` rule, producing the
     *     observed `/explore/projects` -> `/dashboard` symptom).
     */
    async initialize(options: { silent?: boolean } = {}): Promise<void> {
      const silent = options.silent ?? false;
      state.isLoading = true;
      try {
        // If no access token in memory (e.g., after a page reload), attempt
        // to restore it via the refresh token cookie before fetching the user.
        if (!apiClient.getAccessToken()) {
          try {
            await apiClient.refreshToken();
          } catch {
            // Refresh failed - no valid session exists.
            state.user = null;
            state.isAuthenticated = false;
            apiClient.setAccessToken(null);
            state.isLoading = false;
            // Round 2 Major fix: silent refresh failure must also clear
            // the HttpOnly `echoroo_logged_in` marker cookie. Without
            // this, `hooks.server.ts` continues to treat the visitor as
            // authenticated and bounces `/login` back to `/dashboard`,
            // wedging the user out of the recovery flow. We fire-and-
            // forget the logout endpoint (CSRF-exempt, idempotent — see
            // `auth.py::auth_logout`) so cookie eviction always happens
            // regardless of API success.
            await clearMarkerCookieBestEffort();
            if (!silent) {
              await goto(localizeHref('/login'), { replaceState: true });
            }
            return;
          }
        }

        // Access token is now available; fetch the current user.
        const user = await apiClient.get<User>('/api/v1/users/me');
        state.user = user;
        state.isAuthenticated = true;
      } catch (error) {
        // Clear client-side session state
        state.user = null;
        state.isAuthenticated = false;
        apiClient.setAccessToken(null);

        // If the error is a 401 (unauthorized), the refresh token is also invalid.
        // Redirect to login so the user can re-authenticate, unless we are
        // running in silent mode for a public/auth route.
        const isUnauthorized =
          error instanceof Error &&
          'status' in error &&
          (error as { status: number }).status === 401;

        if (isUnauthorized) {
          // Round 2 Major fix: a 401 from `/users/me` after a successful
          // refresh means the session is unrecoverable. Always evict the
          // marker cookie so subsequent navigations stop being treated
          // as authenticated.
          await clearMarkerCookieBestEffort();
        }

        if (isUnauthorized && !silent) {
          // Use replace to avoid adding login to the back-navigation stack
          await goto(localizeHref('/login'), { replaceState: true });
        }
      } finally {
        state.isLoading = false;
      }
    },

    /**
     * Login with email and password
     */
    async login(credentials: LoginCredentials): Promise<void> {
      state.isLoading = true;
      try {
        const response = await apiClient.post<LoginResponse>(
          '/api/v1/auth/login',
          credentials
        );

        // Store access token in API client
        apiClient.setAccessToken(response.access_token);

        // Update state with user data
        state.user = response.user;
        state.isAuthenticated = true;
      } catch (error) {
        state.user = null;
        state.isAuthenticated = false;
        throw error;
      } finally {
        state.isLoading = false;
      }
    },

    /**
     * Logout and clear session.
     *
     * Routes through the new first-party `/web-api/v1/auth/logout` endpoint
     * (via `web-auth.ts`) so the request:
     *   - sends `X-CSRF-Token` (Phase 4 CSRF middleware requires it),
     *   - clears the `echoroo_logged_in` marker cookie (otherwise
     *     `hooks.server.ts` continues to think the user is signed in),
     *   - clears the session/refresh/csrf cookies on the right paths.
     *
     * NOTE: We deliberately do NOT call the legacy `/api/v1/auth/logout`
     * here. That endpoint writes a Redis-backed `revoked_user:{user_id}`
     * marker (TTL = JWT_REFRESH_TOKEN_EXPIRE_DAYS) that the legacy
     * `AuthService.get_current_user` checks on every Bearer call. If we
     * called it on logout, the marker would persist across the user's
     * NEXT login flow and 401 every subsequent `/api/v1/users/me` call
     * for days — which is the regression observed after Round 2
     * (re-login → 2FA challenge 200 → /users/me 401 → refresh 401 → loop).
     * The new web-auth flow already revokes the refresh-token family in
     * `SqlTokenStore` and clears all session cookies, so the legacy
     * fallback is unnecessary as well as harmful.
     */
    async logout(): Promise<void> {
      state.isLoading = true;
      try {
        // Primary (and only) logout call: new web-auth endpoint clears
        // the modern cookies and revokes the refresh family. See the
        // docstring above for why the legacy endpoint is intentionally
        // NOT called.
        await webLogoutUser();
      } catch (error) {
        // Continue with logout even if API call fails.
        console.error('Web logout API call failed:', error);
      }
      // Clear client-side state regardless of API outcomes.
      apiClient.setAccessToken(null);
      state.user = null;
      state.isAuthenticated = false;
      state.isLoading = false;
    },

    /**
     * Refresh access token via the first-party web-auth endpoint.
     *
     * Uses `/web-api/v1/auth/refresh` (not the legacy `/api/v1/auth/refresh`)
     * because the modern flow's refresh cookie is `echoroo_refresh` scoped
     * to `/web-api/v1/auth/refresh`. The legacy endpoint reads a different
     * cookie (`refresh_token`) which the modern login flow never sets, so
     * calling it would always 401 and trigger the `onRefreshFailed` cleanup.
     */
    async refresh(): Promise<void> {
      try {
        const response = await apiClient.post<LoginResponse>(
          '/web-api/v1/auth/refresh'
        );

        // Store new access token
        apiClient.setAccessToken(response.access_token);

        // Update user data
        state.user = response.user;
        state.isAuthenticated = true;
      } catch (error) {
        // Refresh failed, clear session
        apiClient.setAccessToken(null);
        state.user = null;
        state.isAuthenticated = false;
        throw error;
      }
    },
  };
}

export const authStore = createAuthStore();

/**
 * Path prefixes that must NOT trigger an automatic redirect to /login when
 * a background `/api/v1/auth/refresh` call fails. These correspond to the
 * `(public)` and `(auth)` SvelteKit route groups: a Guest browsing a
 * public Explore page or sitting on the login page itself should never be
 * navigated away by an in-flight refresh failure (Phase 4-5-6 carry-over
 * fix #3 for the `/en/explore/projects` -> `/en/dashboard` rerouting bug).
 *
 * The matcher is purposefully prefix-based so it works for both bare and
 * locale-prefixed URLs (`/explore/...`, `/en/explore/...`, `/ja/login` ...).
 */
const NO_REDIRECT_PATH_SEGMENTS = [
  '/explore',
  '/invite',
  '/login',
  '/register',
  '/forgot-password',
  '/reset-password',
  '/verify-email',
  '/2fa',
];

function isOnNoRedirectPath(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  // Strip a leading `/<2-letter locale>` segment (e.g. `/en`, `/ja`) before
  // matching so locale-prefixed routes are detected too.
  const path = window.location.pathname.replace(/^\/[a-z]{2}(?=\/|$)/, '');
  return NO_REDIRECT_PATH_SEGMENTS.some(
    (prefix) => path === prefix || path.startsWith(`${prefix}/`)
  );
}

// Wire up the apiClient refresh failure callback so that when a background
// request fails to refresh (e.g., mid-session expiry), the auth store is
// cleared and the user is redirected to login — UNLESS the user is on a
// public / auth route, in which case we only clear local state and let the
// page render normally.
apiClient.onRefreshFailed = () => {
  authStore.clearUser();
  // Round 2 Major fix: drive the marker cookie clear through the
  // CSRF-exempt logout endpoint. Without this the `echoroo_logged_in`
  // HttpOnly cookie persists, `hooks.server.ts` keeps thinking the user
  // is authenticated, and `/login` redirects to `/dashboard` in a loop.
  // Fire-and-forget — see `clearMarkerCookieBestEffort` for rationale.
  void clearMarkerCookieBestEffort();
  if (isOnNoRedirectPath()) {
    return;
  }
  goto(localizeHref('/login'), { replaceState: true }).catch(() => {
    // If SvelteKit navigation is not available (e.g., during SSR), fall back to hard redirect
    if (typeof window !== 'undefined') {
      window.location.href = localizeHref('/login');
    }
  });
};
