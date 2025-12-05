/**
 * H3 utility functions for geospatial operations.
 *
 * This module provides helper functions for working with H3 hexagonal
 * hierarchical spatial indexing system, particularly for integration
 * with Leaflet maps which expect [lat, lng] coordinate format.
 */
import { cellToLatLng, cellToBoundary, isValidCell } from "h3-js";

/** Default map center coordinates (Tokyo, Japan) */
export const DEFAULT_MAP_CENTER: [number, number] = [35.681236, 139.767125];

/** Default map zoom level */
export const DEFAULT_MAP_ZOOM = 4;

/**
 * Get H3 cell boundary coordinates formatted for Leaflet.
 *
 * h3-js cellToBoundary returns coordinates in [lng, lat] format (GeoJSON),
 * but Leaflet expects [lat, lng] format. This function performs the conversion.
 *
 * @param h3Index - Valid H3 index string
 * @returns Array of [lat, lng] coordinate pairs forming the hexagon boundary
 */
export function getH3BoundaryForLeaflet(h3Index: string): [number, number][] {
  // cellToBoundary with formatAsGeoJson=true returns [lng, lat]
  const boundary = cellToBoundary(h3Index, true);
  // Convert to Leaflet format [lat, lng]
  return boundary.map(([lng, lat]: [number, number]) => [lat, lng]);
}

/**
 * Get H3 cell center coordinates formatted for Leaflet.
 *
 * h3-js cellToLatLng returns [lat, lng] which matches Leaflet's expected format.
 *
 * @param h3Index - Valid H3 index string
 * @returns [lat, lng] coordinate pair for the cell center
 */
export function getH3CenterForLeaflet(h3Index: string): [number, number] {
  return cellToLatLng(h3Index) as [number, number];
}

/**
 * Validate if a string is a valid H3 index.
 *
 * Type guard function that checks if the provided value is a non-null,
 * non-undefined string that represents a valid H3 cell.
 *
 * @param h3Index - Value to validate
 * @returns True if the value is a valid H3 index string
 */
export function isValidH3Index(
  h3Index: string | null | undefined,
): h3Index is string {
  if (h3Index == null || h3Index === "") {
    return false;
  }
  return isValidCell(h3Index);
}

/**
 * Get coordinates from a recording object.
 *
 * Prioritizes direct latitude/longitude values if available,
 * otherwise calculates center coordinates from h3_index.
 *
 * @param recording - Object containing optional location data
 * @returns Object with lat/lng properties, or null if no valid location
 */
export function getRecordingCoordinates(recording: {
  latitude?: number | null;
  longitude?: number | null;
  h3_index?: string | null;
}): { lat: number; lng: number } | null {
  const { latitude, longitude, h3_index } = recording;

  // Prioritize direct lat/lon values
  if (latitude != null && longitude != null) {
    return { lat: latitude, lng: longitude };
  }

  // Fallback to h3_index center
  if (isValidH3Index(h3_index)) {
    try {
      const [lat, lng] = getH3CenterForLeaflet(h3_index);
      return { lat, lng };
    } catch {
      // Invalid h3_index, return null
      return null;
    }
  }

  return null;
}
