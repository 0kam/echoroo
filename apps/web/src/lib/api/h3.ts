/**
 * H3 utility API client.
 */

import type {
  H3FromCoordinatesRequest,
  H3FromCoordinatesResponse,
  H3ValidationResponse,
} from '$lib/types/data';

const API_BASE = '/api/v1';

/**
 * Validate an H3 index.
 */
export async function validateH3Index(h3Index: string): Promise<H3ValidationResponse> {
  const response = await fetch(`${API_BASE}/h3/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ h3_index: h3Index }),
  });

  if (!response.ok) {
    throw new Error('Failed to validate H3 index');
  }

  return response.json();
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

  const response = await fetch(`${API_BASE}/h3/from-coordinates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Failed to get H3 index' }));
    throw new Error(error.detail || 'Failed to get H3 index');
  }

  return response.json();
}
