/**
 * H3 utility API client.
 */

import type {
  H3FromCoordinatesRequest,
  H3FromCoordinatesResponse,
  H3ValidationResponse,
} from '$lib/types/data';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

const API_BASE = '/api/v1';

/**
 * Validate an H3 index.
 */
export async function validateH3Index(h3Index: string): Promise<H3ValidationResponse> {
  const response = await fetchWithErrorHandling(`${API_BASE}/h3/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ h3_index: h3Index }),
  });

  return handleApiResponse<H3ValidationResponse>(response);
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

  const response = await fetchWithErrorHandling(`${API_BASE}/h3/from-coordinates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });

  return handleApiResponse<H3FromCoordinatesResponse>(response);
}
