"use client";

import { useEffect, useState } from "react";
import {
  MapContainer,
  Marker,
  Polygon,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type { Map as LeafletMap } from "leaflet";
import { latLngToCell, cellToLatLng, cellToBoundary, isValidCell } from "h3-js";
import L from "leaflet";

type H3HexPickerProps = {
  value?: string | null;
  onChange?: (h3Index: string) => void;
  resolution?: number;
  onResolutionChange?: (resolution: number) => void;
  height?: number;
};

const DEFAULT_RESOLUTION = 12;
const DEFAULT_CENTER: [number, number] = [35.681236, 139.767125];
const DEFAULT_ZOOM = 6;

const pickerMarkerIcon = new L.Icon({
  iconUrl:
    "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-orange.png",
  shadowUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

/**
 * Component to handle map resize when container becomes visible
 */
function MapResizeHandler() {
  const map = useMap();

  useEffect(() => {
    // Use ResizeObserver to detect when the map container becomes visible or resizes
    const container = map.getContainer();
    const resizeObserver = new ResizeObserver(() => {
      // Small delay to ensure the container has finished animating
      setTimeout(() => {
        map.invalidateSize();
      }, 100);
    });
    resizeObserver.observe(container);

    // Also invalidate on initial mount after a short delay
    const timeoutId = setTimeout(() => {
      map.invalidateSize();
    }, 300);

    return () => {
      resizeObserver.disconnect();
      clearTimeout(timeoutId);
    };
  }, [map]);

  return null;
}

function HexLayer({
  value,
  onChange,
  resolution,
}: {
  value?: string | null;
  onChange?: (h3Index: string) => void;
  resolution: number;
}) {
  const [hoverCell, setHoverCell] = useState<string | null>(null);

  const map = useMapEvents({
    click(event) {
      try {
        const { lat, lng } = event.latlng;
        // Validate coordinates before generating H3 cell
        if (
          lat == null ||
          lng == null ||
          !Number.isFinite(lat) ||
          !Number.isFinite(lng)
        ) {
          console.error("[H3HexPicker] Invalid coordinates:", { lat, lng });
          return;
        }
        const next = latLngToCell(lat, lng, resolution);
        if (next && isValidCell(next)) {
          onChange?.(next);
        } else {
          console.error("[H3HexPicker] Generated invalid H3 cell:", next);
        }
      } catch (error) {
        console.error("[H3HexPicker] Error generating H3 cell:", error);
      }
    },
    mousemove(event) {
      try {
        const { lat, lng } = event.latlng;
        if (
          lat == null ||
          lng == null ||
          !Number.isFinite(lat) ||
          !Number.isFinite(lng)
        ) {
          return;
        }
        const cell = latLngToCell(lat, lng, resolution);
        if (cell !== hoverCell) {
          setHoverCell(cell);
        }
      } catch (error) {
        // Silently ignore mousemove errors
      }
    },
    mouseout() {
      setHoverCell(null);
    },
  });

  useEffect(() => {
    if (!value || !isValidCell(value)) return;
    try {
      const [lat, lng] = cellToLatLng(value);
      const targetZoom = Math.max(map.getZoom(), 10);
      (map as LeafletMap).flyTo({ lat, lng }, targetZoom, {
        animate: true,
        duration: 0.4,
      });
    } catch (error) {
      console.error("[H3HexPicker] Error flying to cell:", error);
    }
  }, [value, map]);

  // Render hover preview
  // Note: cellToBoundary returns [lng, lat] but Leaflet expects [lat, lng]
  const hoverBoundary = hoverCell && hoverCell !== value
    ? (cellToBoundary(hoverCell, true).map(
      ([lng, lat]: [number, number]) => [lat, lng],
    ) as [number, number][])
    : null;

  // Render selected cell
  // Note: cellToBoundary returns [lng, lat] but Leaflet expects [lat, lng]
  const selectedBoundary = value
    ? (cellToBoundary(value, true).map(
      ([lng, lat]: [number, number]) => [lat, lng],
    ) as [number, number][])
    : null;
  const selectedCenter = value ? (cellToLatLng(value) as [number, number]) : null;

  return (
    <>
      {hoverBoundary && (
        <Polygon
          positions={hoverBoundary}
          pathOptions={{
            color: "#6366f1",
            weight: 2,
            fillOpacity: 0.15,
            dashArray: "5, 5",
          }}
        />
      )}
      {selectedBoundary && (
        <Polygon
          positions={selectedBoundary}
          pathOptions={{
            color: "#10b981",
            weight: 3,
            fillOpacity: 0.3,
          }}
        />
      )}
      {selectedCenter && (
        <Marker
          position={{ lat: selectedCenter[0], lng: selectedCenter[1] }}
          icon={pickerMarkerIcon}
        >
          <Tooltip>
            <div className="space-y-1">
              <div className="font-semibold text-sm text-stone-800">
                選択中のサイト
              </div>
              <div className="font-mono text-xs text-stone-500">
                {value}
              </div>
              <div className="text-xs text-stone-500">
                {selectedCenter[0].toFixed(5)}, {selectedCenter[1].toFixed(5)}
              </div>
            </div>
          </Tooltip>
        </Marker>
      )}
    </>
  );
}

// H3 resolution reference information
const H3_RESOLUTION_INFO = [
  { res: 0, avgEdge: "1107.71 km", avgArea: "4,357,449 km²" },
  { res: 1, avgEdge: "418.68 km", avgArea: "609,788 km²" },
  { res: 2, avgEdge: "158.24 km", avgArea: "86,801 km²" },
  { res: 3, avgEdge: "59.81 km", avgArea: "12,393 km²" },
  { res: 4, avgEdge: "22.61 km", avgArea: "1,770 km²" },
  { res: 5, avgEdge: "8.54 km", avgArea: "252.9 km²" },
  { res: 6, avgEdge: "3.23 km", avgArea: "36.1 km²" },
  { res: 7, avgEdge: "1.22 km", avgArea: "5.2 km²" },
  { res: 8, avgEdge: "461.35 m", avgArea: "737,327 m²" },
  { res: 9, avgEdge: "174.38 m", avgArea: "105,332 m²" },
  { res: 10, avgEdge: "65.91 m", avgArea: "15,047 m²" },
  { res: 11, avgEdge: "24.91 m", avgArea: "2,150 m²" },
  { res: 12, avgEdge: "9.42 m", avgArea: "307.7 m²" },
  { res: 13, avgEdge: "3.56 m", avgArea: "43.9 m²" },
  { res: 14, avgEdge: "1.35 m", avgArea: "6.3 m²" },
  { res: 15, avgEdge: "0.51 m", avgArea: "0.9 m²" },
];

export default function H3HexPicker({
  value,
  onChange,
  resolution = DEFAULT_RESOLUTION,
  onResolutionChange,
  height = 480,
}: H3HexPickerProps) {
  // Safely compute center - use default if value is invalid
  let center: [number, number] = DEFAULT_CENTER;
  if (value && isValidCell(value)) {
    try {
      center = cellToLatLng(value) as [number, number];
    } catch {
      // Fall back to default center
    }
  }


  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <label className="text-sm font-medium text-stone-700 dark:text-stone-300">
            H3 解像度: {resolution}
          </label>
          <span className="text-xs text-stone-500 dark:text-stone-400">
            セルサイズ: {H3_RESOLUTION_INFO[resolution]?.avgEdge} (面積: {H3_RESOLUTION_INFO[resolution]?.avgArea})
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-stone-500 dark:text-stone-400 w-8">粗</span>
          <input
            type="range"
            min="0"
            max="15"
            value={resolution}
            onChange={(e) => onResolutionChange?.(Number(e.target.value))}
            className="flex-1 h-2 bg-stone-200 dark:bg-stone-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
          />
          <span className="text-xs text-stone-500 dark:text-stone-400 w-8">細</span>
        </div>
      </div>

      <div className="rounded-lg overflow-hidden border border-stone-200 dark:border-stone-700">
        <MapContainer
          center={{ lat: center[0], lng: center[1] }}
          zoom={value ? 10 : DEFAULT_ZOOM}
          scrollWheelZoom={true}
          style={{ height }}
        >
          <MapResizeHandler />
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <HexLayer value={value} onChange={onChange} resolution={resolution} />
        </MapContainer>
      </div>

      <div className="text-xs text-stone-500 dark:text-stone-400">
        💡 マップをクリックしてセルを選択してください。マウスカーソルを動かすとセルのプレビューが表示されます。
      </div>
    </div>
  );
}
