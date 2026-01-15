"use client";

import { useEffect, useMemo, useRef } from "react";
import { useMap } from "react-leaflet";
import type { LatLngExpression } from "leaflet";

export interface MapViewportProps {
  /** The center position to navigate to */
  center: LatLngExpression;
  /** Optional zoom level. If not provided, maintains current zoom */
  zoom?: number;
  /** Whether to animate the transition. Defaults to true */
  animate?: boolean;
}

/** Helper to normalize LatLngExpression to [lat, lng] tuple */
function normalizeCenter(center: LatLngExpression): [number, number] {
  if (Array.isArray(center)) {
    return [center[0], center[1]];
  }
  if ("lat" in center && "lng" in center) {
    return [center.lat, center.lng];
  }
  return [0, 0];
}

/**
 * A utility component that controls the map viewport.
 * Must be used as a child of MapContainer.
 */
export default function MapViewport({
  center,
  zoom,
  animate = true,
}: MapViewportProps) {
  const map = useMap();
  const isInitializedRef = useRef(false);

  // Normalize center to primitives to avoid object identity issues
  const [lat, lng] = useMemo(() => normalizeCenter(center), [center]);

  useEffect(() => {
    if (!map) return;

    const targetZoom = zoom ?? map.getZoom();

    if (!isInitializedRef.current) {
      // Initial setup - wait for map to be ready
      map.whenReady(() => {
        map.setView([lat, lng], targetZoom, { animate: false });
        isInitializedRef.current = true;
      });
    } else {
      // Subsequent updates
      map.setView([lat, lng], targetZoom, { animate });
    }
  }, [lat, lng, zoom, animate, map]);

  return null;
}
