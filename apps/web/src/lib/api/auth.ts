/**
 * Authentication API client
 * Handles login, registration, password reset, and email verification
 */

import { apiClient } from './client';
import type {
  User,
  LoginRequest,
  UserRegisterRequest,
  TokenResponse,
} from '$lib/types';

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
 * Login with email and password
 */
export async function login(data: LoginRequest): Promise<LoginResponse> {
  return apiClient.post<LoginResponse>('/api/v1/auth/login', data);
}

/**
 * Register new user account
 */
export async function register(data: UserRegisterRequest): Promise<RegisterResponse> {
  return apiClient.post<RegisterResponse>('/api/v1/auth/register', data);
}

/**
 * Logout current user (clears refresh token cookie)
 */
export async function logout(): Promise<void> {
  await apiClient.post('/api/v1/auth/logout');
}

/**
 * Refresh access token using refresh token cookie
 */
export async function refreshToken(): Promise<TokenResponse> {
  return apiClient.post<TokenResponse>('/api/v1/auth/refresh');
}

/**
 * Request password reset email
 */
export async function requestPasswordReset(email: string): Promise<MessageResponse> {
  return apiClient.post<MessageResponse>('/api/v1/auth/password-reset/request', { email });
}

/**
 * Confirm password reset with token
 */
export async function confirmPasswordReset(
  token: string,
  password: string
): Promise<MessageResponse> {
  return apiClient.post<MessageResponse>('/api/v1/auth/password-reset/confirm', {
    token,
    password,
  });
}

/**
 * Verify email address with token
 */
export async function verifyEmail(token: string): Promise<MessageResponse> {
  return apiClient.post<MessageResponse>('/api/v1/auth/verify-email', { token });
}

/**
 * Get current authenticated user.
 *
 * Uses the BFF cookie + CSRF surface at ``/web-api/v1/users/me`` so
 * post-2FA browser sessions (which carry only the session cookie and
 * NOT a Bearer-JWT header) succeed instead of triggering the
 * auto-logout regression observed after spec/006's auth migration.
 */
export async function getCurrentUser(): Promise<User> {
  return apiClient.get<User>('/web-api/v1/users/me');
}

/**
 * Resend email verification
 */
export async function resendVerificationEmail(): Promise<MessageResponse> {
  return apiClient.post<MessageResponse>('/api/v1/auth/verify-email/resend');
}
