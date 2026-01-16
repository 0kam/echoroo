/**
 * API Token management API client
 */

import { apiClient } from './client';
import type { APIToken, APITokenCreateRequest, APITokenCreateResponse } from '$lib/types';

/**
 * List all active API tokens for the current user
 */
export async function listTokens(): Promise<APIToken[]> {
  return apiClient.get<APIToken[]>('/api/v1/users/me/api-tokens');
}

/**
 * Create a new API token
 * The token value is returned only once
 */
export async function createToken(
  request: APITokenCreateRequest
): Promise<APITokenCreateResponse> {
  return apiClient.post<APITokenCreateResponse>('/api/v1/users/me/api-tokens', request);
}

/**
 * Revoke an API token
 */
export async function revokeToken(tokenId: string): Promise<void> {
  return apiClient.delete<void>(`/api/v1/users/me/api-tokens/${tokenId}`);
}
