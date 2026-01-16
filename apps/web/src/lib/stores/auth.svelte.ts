/**
 * Authentication store using Svelte 5 runes
 */

import type { User } from '$lib/types';
import { apiClient } from '$lib/api/client';

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
     * Initialize auth state by checking current session
     */
    async initialize(): Promise<void> {
      state.isLoading = true;
      try {
        // Try to get current user from backend
        const user = await apiClient.get<User>('/api/auth/me');
        state.user = user;
        state.isAuthenticated = true;
      } catch {
        // Not authenticated or session expired
        state.user = null;
        state.isAuthenticated = false;
        apiClient.setAccessToken(null);
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
          '/api/auth/login',
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
        await apiClient.post('/api/auth/logout');
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
          '/api/auth/refresh'
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
