/**
 * H3 utility API client.
 */

import type {
  H3FromCoordinatesRequest,
  H3FromCoordinatesResponse,
  H3ValidationResponse,
} from '$lib/types/data';
import { apiClient } from './client';

const API_BASE = '/api/v1';

/**
 * Validate an H3 index.
 */
export async function validateH3Index(h3Index: string): Promise<H3ValidationResponse> {
  return apiClient.post<H3ValidationResponse>(`${API_BASE}/h3/validate`, { h3_index: h3Index });
}

/**
 * Get H3 index from coordinates.
 */
export async function getH3FromCoordinates(
  latitude: number,
  longitude: number,
  resolution: number
): Promise<H3FromCoordinatesResponse> {
  const request: H3FromCoordinatesRequest = { latitude, longitude, resolution };
  return apiClient.post<H3FromCoordinatesResponse>(`${API_BASE}/h3/from-coordinates`, request);
}
