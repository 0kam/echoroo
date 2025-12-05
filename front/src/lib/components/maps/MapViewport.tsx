"use client";

import { useEffect } from "react";
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

  useEffect(() => {
    if (!map) return;

    // Wait for map to be ready
    map.whenReady(() => {
      const targetZoom = zoom ?? map.getZoom();
      map.setView(center, targetZoom, { animate });
    });
  }, [center, zoom, animate, map]);

  return null;
}
