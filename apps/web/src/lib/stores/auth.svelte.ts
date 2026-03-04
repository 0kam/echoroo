/**
 * Authentication store using Svelte 5 runes
 */

import type { User } from '$lib/types';
import { apiClient } from '$lib/api/client';
import { goto } from '$app/navigation';

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
     * If the session is invalid (e.g., expired/revoked refresh token),
     * clears the client state and redirects to the login page.
     */
    async initialize(): Promise<void> {
      state.isLoading = true;
      try {
        // Try to get current user; this will attempt a token refresh internally
        // if the access token is missing or expired.
        const user = await apiClient.get<User>('/api/v1/users/me');
        state.user = user;
        state.isAuthenticated = true;
      } catch (error) {
        // Clear client-side session state
        state.user = null;
        state.isAuthenticated = false;
        apiClient.setAccessToken(null);

        // If the error is a 401 (unauthorized), the refresh token is also invalid.
        // Redirect to login so the user can re-authenticate.
        const isUnauthorized =
          error instanceof Error &&
          'status' in error &&
          (error as { status: number }).status === 401;

        if (isUnauthorized) {
          // Use replace to avoid adding login to the back-navigation stack
          await goto('/login', { replaceState: true });
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
     * Logout and clear session
     */
    async logout(): Promise<void> {
      state.isLoading = true;
      try {
        // Call logout endpoint to clear refresh token cookie
        await apiClient.post('/api/v1/auth/logout');
      } catch (error) {
        // Continue with logout even if API call fails
        console.error('Logout API call failed:', error);
      } finally {
        // Clear client-side state
        apiClient.setAccessToken(null);
        state.user = null;
        state.isAuthenticated = false;
        state.isLoading = false;
      }
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

// Wire up the apiClient refresh failure callback so that when a background
// request fails to refresh (e.g., mid-session expiry), the auth store is
// cleared and the user is redirected to login.
apiClient.onRefreshFailed = () => {
  authStore.clearUser();
  goto('/login', { replaceState: true }).catch(() => {
    // If SvelteKit navigation is not available (e.g., during SSR), fall back to hard redirect
    if (typeof window !== 'undefined') {
      window.location.href = '/login';
    }
  });
};
