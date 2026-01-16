/**
 * Base API client for Echoroo backend
 */

/**
 * Custom error class for API errors
 */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Get API URL from environment or default
 */
function getApiUrl(): string {
  // Try to get from window (browser environment)
  if (typeof window !== 'undefined') {
    return (
      (window as any).__PUBLIC_API_URL__ ||
      import.meta.env.PUBLIC_API_URL ||
      'http://localhost:8000'
    );
  }
  // Server-side or build-time
  return import.meta.env.PUBLIC_API_URL || 'http://localhost:8000';
}

export class ApiClient {
  private baseUrl: string;
  private accessToken: string | null = null;
  private refreshPromise: Promise<void> | null = null;

  constructor(baseUrl?: string) {
    this.baseUrl = baseUrl || getApiUrl();
  }

  /**
   * Set access token for authenticated requests
   */
  setAccessToken(token: string | null) {
    this.accessToken = token;
  }

  /**
   * Get current access token
   */
  getAccessToken(): string | null {
    return this.accessToken;
  }

  /**
   * Refresh access token using refresh token from cookie
   */
  private async refreshAccessToken(): Promise<void> {
    // If already refreshing, wait for that promise
    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    this.refreshPromise = (async () => {
      try {
        const response = await fetch(`${this.baseUrl}/api/auth/refresh`, {
          method: 'POST',
          credentials: 'include', // Send refresh token cookie
          headers: {
            'Content-Type': 'application/json',
          },
        });

        if (!response.ok) {
          throw new ApiError('Token refresh failed', response.status);
        }

        const data = await response.json();
        this.accessToken = data.access_token;
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

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    // Add Authorization header if access token exists
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

    const config: RequestInit = {
      ...options,
      credentials: 'include', // Include cookies for refresh token
      headers,
    };

    let response = await fetch(url, config);

    // Handle 401 Unauthorized - try to refresh token
    if (response.status === 401 && retry) {
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
          errorData.detail || 'Unauthorized',
          401,
          errorData.detail
        );
      }
    }

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({
        detail: 'An error occurred',
      }));
      throw new ApiError(
        errorData.detail || 'Request failed',
        response.status,
        errorData.detail
      );
    }

    // Handle empty responses (e.g., 204 No Content)
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

  async delete<T>(endpoint: string, options?: RequestInit): Promise<T> {
    return this.request<T>(endpoint, { ...options, method: 'DELETE' });
  }
}

// Export singleton instance
export const apiClient = new ApiClient();
