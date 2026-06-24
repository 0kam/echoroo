/**
 * API Token management API client.
 *
 * W2-2: the self-scoped ``/users/me/api-tokens`` endpoints resolve through
 * the BFF cookie + CSRF surface (``/web-api/v1/users/me/api-tokens``), each
 * delegating verbatim to the legacy ``/api/v1`` handler server-side.
 * Mutations attach ``X-CSRF-Token`` via the inline ``csrfHeaders()`` helper.
 */

import { apiClient } from './client';
import type { APIToken, APITokenCreateRequest, APITokenCreateResponse } from '$lib/types';

const CSRF_COOKIE_NAME = 'echoroo_csrf';

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

function csrfHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getCsrfToken();
  if (token) headers['X-CSRF-Token'] = token;
  return headers;
}

/**
 * List all active API tokens for the current user
 */
export async function listTokens(): Promise<APIToken[]> {
  return apiClient.get<APIToken[]>('/web-api/v1/users/me/api-tokens');
}

/**
 * Create a new API token
 * The token value is returned only once
 */
export async function createToken(
  request: APITokenCreateRequest
): Promise<APITokenCreateResponse> {
  return apiClient.post<APITokenCreateResponse>(
    '/web-api/v1/users/me/api-tokens',
    request,
    { headers: csrfHeaders() }
  );
}

/**
 * Revoke an API token
 */
export async function revokeToken(tokenId: string): Promise<void> {
  return apiClient.delete<void>(
    `/web-api/v1/users/me/api-tokens/${tokenId}`,
    { headers: csrfHeaders() }
  );
}
