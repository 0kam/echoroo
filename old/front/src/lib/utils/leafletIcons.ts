import L from "leaflet";

/**
 * Available marker colors from leaflet-color-markers
 */
export type MarkerColor =
  | "blue"
  | "green"
  | "orange"
  | "red"
  | "yellow"
  | "violet"
  | "grey"
  | "black";

/**
 * Available marker sizes
 */
export type MarkerSize = "normal" | "large";

/**
 * Base URL for leaflet-color-markers icons
 */
const MARKER_ICON_BASE_URL =
  "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img";

/**
 * Icon dimensions for each size
 */
const ICON_SIZES: Record<MarkerSize, { size: [number, number]; anchor: [number, number] }> = {
  normal: {
    size: [25, 41],
    anchor: [12, 41],
  },
  large: {
    size: [30, 49],
    anchor: [15, 49],
  },
};

/**
 * Cache for marker icons to avoid creating duplicate instances
 */
const iconCache = new Map<string, L.Icon>();

/**
 * Generate a cache key for a marker icon
 */
function getCacheKey(color: MarkerColor, size: MarkerSize): string {
  return `${color}-${size}`;
}

/**
 * Get a marker icon with the specified color and size.
 * Icons are cached to avoid creating duplicate instances.
 *
 * @param color - The color of the marker
 * @param size - The size of the marker (default: "normal")
 * @returns A Leaflet Icon instance
 */
export function getMarkerIcon(color: MarkerColor, size: MarkerSize = "normal"): L.Icon {
  const cacheKey = getCacheKey(color, size);

  const cachedIcon = iconCache.get(cacheKey);
  if (cachedIcon) {
    return cachedIcon;
  }

  const { size: iconSize, anchor: iconAnchor } = ICON_SIZES[size];

  const icon = new L.Icon({
    iconUrl: `${MARKER_ICON_BASE_URL}/marker-icon-2x-${color}.png`,
    shadowUrl: `${MARKER_ICON_BASE_URL}/marker-shadow.png`,
    iconSize,
    iconAnchor,
    popupAnchor: [1, -34],
    shadowSize: [41, 41],
  });

  iconCache.set(cacheKey, icon);

  return icon;
}

/**
 * Get the appropriate marker color based on visibility status.
 * - Public datasets/recordings use green markers
 * - Restricted (private/internal) datasets/recordings use orange markers
 *
 * @param hasRestricted - Whether the item has restricted visibility
 * @returns The appropriate marker color
 */
export function getVisibilityMarkerColor(hasRestricted: boolean): MarkerColor {
  return hasRestricted ? "orange" : "green";
}

/**
 * Clear the icon cache (useful for testing or memory management)
 */
export function clearIconCache(): void {
  iconCache.clear();
}
