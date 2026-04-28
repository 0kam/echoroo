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
     * The legacy `/api/v1/auth/logout` is also called as a transition
     * fallback so any not-yet-migrated legacy `refresh_token` cookie is
     * still cleared. Both calls swallow their own errors so client-side
     * state is always reset.
     */
    async logout(): Promise<void> {
      state.isLoading = true;
      try {
        // Primary: new web-auth endpoint (clears the new cookies).
        await webLogoutUser();
      } catch (error) {
        // Continue with logout even if API call fails.
        console.error('Web logout API call failed:', error);
      }
      try {
        // Transition fallback: clear any remaining legacy cookies. Safe to
        // call after the new endpoint and harmless if no legacy session exists.
        await apiClient.post('/api/v1/auth/logout');
      } catch (error) {
        // Legacy endpoint failure is non-fatal once the new endpoint succeeded.
        console.warn('Legacy logout API call failed:', error);
      }
      // Clear client-side state regardless of API outcomes.
      apiClient.setAccessToken(null);
      state.user = null;
      state.isAuthenticated = false;
      state.isLoading = false;
    },

    /**
     * Refresh access token
     */
    async refresh(): Promise<void> {
      try {
        const response = await apiClient.post<LoginResponse>(
          '/api/v1/auth/refresh'
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
