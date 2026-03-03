/**
 * API error handling utilities.
 */

import { apiClient } from './client';

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
    public code?: string,
    public details?: Record<string, unknown>
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Handle fetch response and convert errors to user-friendly messages.
 */
export async function handleApiResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    return response.json();
  }

  let errorMessage = 'An unexpected error occurred';
  let errorCode: string | undefined;
  let errorDetails: Record<string, unknown> | undefined;

  try {
    const errorData = await response.json();

    // FastAPI error format
    if (errorData.detail) {
      if (typeof errorData.detail === 'string') {
        errorMessage = errorData.detail;
      } else if (Array.isArray(errorData.detail)) {
        // Validation errors
        const validationErrors = errorData.detail
          .map((err: { loc: string[]; msg: string }) => `${err.loc.join('.')}: ${err.msg}`)
          .join(', ');
        errorMessage = `Validation error: ${validationErrors}`;
      } else if (typeof errorData.detail === 'object') {
        errorMessage = errorData.detail.message || JSON.stringify(errorData.detail);
        errorCode = errorData.detail.code;
        errorDetails = errorData.detail;
      }
    }
  } catch (e) {
    // If we can't parse JSON, use status-based message
    errorMessage = getStatusMessage(response.status);
  }

  throw new ApiError(errorMessage, response.status, errorCode, errorDetails);
}

/**
 * Build request options with authentication headers injected.
 * Merges the Authorization header from apiClient with any existing headers.
 */
function buildAuthOptions(options?: RequestInit): RequestInit {
  const token = apiClient.getAccessToken();
  if (!token) {
    return {
      ...options,
      credentials: 'include' as RequestCredentials,
      signal: AbortSignal.timeout(30000),
    };
  }

  const existingHeaders = options?.headers
    ? Object.fromEntries(new Headers(options.headers).entries())
    : {};

  return {
    ...options,
    credentials: 'include' as RequestCredentials,
    signal: AbortSignal.timeout(30000),
    headers: {
      ...existingHeaders,
      Authorization: `Bearer ${token}`,
    },
  };
}

/**
 * Handle network errors and timeouts.
 * Automatically injects the auth token from apiClient and retries once on 401.
 */
export async function fetchWithErrorHandling(
  url: string,
  options?: RequestInit
): Promise<Response> {
  try {
    const authOptions = buildAuthOptions(options);
    let response = await fetch(url, authOptions);

    // On 401, attempt a token refresh and retry once
    if (response.status === 401) {
      try {
        await apiClient.refreshToken();

        // Retry with the new token
        const retryOptions = buildAuthOptions(options);
        response = await fetch(url, retryOptions);
      } catch {
        // Refresh failed; return the original 401 response so callers
        // can handle it through their normal error path.
        return response;
      }
    }

    return response;
  } catch (error) {
    if (error instanceof Error) {
      if (error.name === 'AbortError' || error.name === 'TimeoutError') {
        throw new ApiError(
          'Request timeout. Please check your connection and try again.',
          0,
          'TIMEOUT'
        );
      }
      if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
        throw new ApiError(
          'Network error. Please check your internet connection.',
          0,
          'NETWORK_ERROR'
        );
      }
    }
    throw error;
  }
}

/**
 * Get user-friendly message based on HTTP status code.
 */
function getStatusMessage(status: number): string {
  switch (status) {
    case 400:
      return 'Invalid request. Please check your input and try again.';
    case 401:
      return 'Authentication required. Please log in.';
    case 403:
      return 'You do not have permission to perform this action.';
    case 404:
      return 'Resource not found.';
    case 409:
      return 'Conflict. The resource already exists or cannot be modified.';
    case 422:
      return 'Validation error. Please check your input.';
    case 429:
      return 'Too many requests. Please wait and try again.';
    case 500:
      return 'Server error. Please try again later.';
    case 502:
    case 503:
      return 'Service temporarily unavailable. Please try again later.';
    case 504:
      return 'Request timeout. Please try again.';
    default:
      return `Request failed with status ${status}`;
  }
}
