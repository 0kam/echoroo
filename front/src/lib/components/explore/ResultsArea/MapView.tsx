"use client";

import { Fragment, useCallback, useMemo, useEffect, useState, memo } from "react";
import {
  MapContainer,
  TileLayer,
  Polygon,
  Marker,
  Popup,
  Tooltip,
  useMap,
  Rectangle,
} from "react-leaflet";
import L from "leaflet";

import Link from "@/lib/components/ui/Link";
import VisibilityBadge from "@/lib/components/ui/VisibilityBadge";
import type { Recording } from "@/lib/types";
import type { DrawnShape } from "@/app/store/explore";
import {
  DEFAULT_MAP_CENTER,
  DEFAULT_MAP_ZOOM,
  getH3BoundaryForLeaflet,
  getH3CenterForLeaflet,
  isValidH3Index,
} from "@/lib/utils/h3";
import {
  getMarkerIcon,
  getVisibilityMarkerColor,
} from "@/lib/utils/leafletIcons";

type MapViewProps = {
  recordings: Recording[];
  drawnShape: DrawnShape | null;
  isLoading: boolean;
};

// H3 cell bucket for aggregated recordings
type H3CellBucket = {
  h3Index: string;
  recordings: Recording[];
  publicCount: number;
  restrictedCount: number;
  center: [number, number];
  boundary: [number, number][];
  siteName: string | null;
  dateRange: {
    earliest: Date;
    latest: Date;
  } | null;
};

// Format date range for display
function formatDateRange(start: Date, end: Date): string {
  const options: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  };

  const startStr = start.toLocaleDateString('en-US', options);
  const endStr = end.toLocaleDateString('en-US', options);

  if (startStr === endStr) {
    return startStr;
  }

  // Same year - shorter format for start date
  if (start.getFullYear() === end.getFullYear()) {
    const shortStart = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    return `${shortStart} - ${endStr}`;
  }

  return `${startStr} - ${endStr}`;
}

// Aggregate recordings by H3 index
function aggregateByH3(recordings: Recording[]): H3CellBucket[] {
  const bucketMap = new Map<
    string,
    {
      recordings: Recording[];
      publicCount: number;
      restrictedCount: number;
      siteNames: string[];
      dates: Date[];
    }
  >();

  for (const recording of recordings) {
    const h3Index = recording.h3_index;
    if (!isValidH3Index(h3Index)) continue;

    if (!bucketMap.has(h3Index)) {
      bucketMap.set(h3Index, {
        recordings: [],
        publicCount: 0,
        restrictedCount: 0,
        siteNames: [],
        dates: [],
      });
    }

    const bucket = bucketMap.get(h3Index)!;
    bucket.recordings.push(recording);

    const visibility = recording.dataset?.visibility ?? "public";
    if (visibility === "public") {
      bucket.publicCount += 1;
    } else {
      bucket.restrictedCount += 1;
    }

    // Collect site names
    const siteName = recording.dataset?.primary_site?.site_name;
    if (siteName) {
      bucket.siteNames.push(siteName);
    }

    // Collect dates
    if (recording.datetime) {
      const date = new Date(recording.datetime);
      if (!isNaN(date.getTime())) {
        bucket.dates.push(date);
      }
    }
  }

  return Array.from(bucketMap.entries()).map(([h3Index, bucket]) => {
    const boundary = getH3BoundaryForLeaflet(h3Index);
    const center = getH3CenterForLeaflet(h3Index);

    // Get most common site name
    let siteName: string | null = null;
    if (bucket.siteNames.length > 0) {
      const siteNameCounts = bucket.siteNames.reduce((acc, name) => {
        acc[name] = (acc[name] || 0) + 1;
        return acc;
      }, {} as Record<string, number>);

      let maxCount = 0;
      for (const [name, count] of Object.entries(siteNameCounts)) {
        if (count > maxCount) {
          maxCount = count;
          siteName = name;
        }
      }
    }

    // Calculate date range
    let dateRange: { earliest: Date; latest: Date } | null = null;
    if (bucket.dates.length > 0) {
      const timestamps = bucket.dates.map(d => d.getTime());
      dateRange = {
        earliest: new Date(Math.min(...timestamps)),
        latest: new Date(Math.max(...timestamps)),
      };
    }

    return {
      h3Index,
      recordings: bucket.recordings,
      publicCount: bucket.publicCount,
      restrictedCount: bucket.restrictedCount,
      center,
      boundary,
      siteName,
      dateRange,
    };
  });
}

// Component to show drawn shape
const DrawnShapeLayer = memo(function DrawnShapeLayer({
  shape,
}: {
  shape: DrawnShape | null;
}) {
  if (!shape) return null;

  const [minLon, minLat, maxLon, maxLat] = shape.bounds;

  return (
    <Rectangle
      bounds={[
        [minLat, minLon],
        [maxLat, maxLon],
      ]}
      pathOptions={{
        color: "#10b981",
        fillOpacity: 0.1,
        dashArray: "5, 5",
      }}
    />
  );
});

// Component to fit map to H3 cells or drawn shape
const FitBounds = memo(function FitBounds({
  cells,
  drawnShape,
}: {
  cells: H3CellBucket[];
  drawnShape: DrawnShape | null;
}) {
  const map = useMap();

  useEffect(() => {
    if (drawnShape) {
      const [minLon, minLat, maxLon, maxLat] = drawnShape.bounds;
      if (
        Number.isFinite(minLon) &&
        Number.isFinite(minLat) &&
        Number.isFinite(maxLon) &&
        Number.isFinite(maxLat)
      ) {
        map.fitBounds([
          [minLat, minLon],
          [maxLat, maxLon],
        ]);
      }
      return;
    }

    if (cells.length === 0) return;

    const lats = cells.map((c) => c.center[0]);
    const lngs = cells.map((c) => c.center[1]);

    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLng = Math.min(...lngs);
    const maxLng = Math.max(...lngs);

    if (
      Number.isFinite(minLat) &&
      Number.isFinite(maxLat) &&
      Number.isFinite(minLng) &&
      Number.isFinite(maxLng)
    ) {
      const bounds = L.latLngBounds([minLat, minLng], [maxLat, maxLng]);
      map.fitBounds(bounds, { padding: [20, 20], maxZoom: 12 });
    }
  }, [cells, drawnShape, map]);

  return null;
});

// H3 Hex cell component with polygon and marker
const H3HexCell = memo(function H3HexCell({
  cell,
  isHighlighted,
  onHover,
}: {
  cell: H3CellBucket;
  isHighlighted: boolean;
  onHover: (h3Index: string | null) => void;
}) {
  const hasRestricted = cell.restrictedCount > 0;
  const baseColor = hasRestricted ? "#f59e0b" : "#10b981";
  const markerColor = getVisibilityMarkerColor(hasRestricted);
  const markerIcon = getMarkerIcon(markerColor, isHighlighted ? "large" : "normal");

  return (
    <Fragment>
      <Polygon
        positions={cell.boundary}
        pathOptions={{
          color: baseColor,
          weight: isHighlighted ? 3 : 1.5,
          fillColor: baseColor,
          fillOpacity: isHighlighted ? 0.4 : 0.2,
        }}
        eventHandlers={{
          mouseover: () => onHover(cell.h3Index),
          mouseout: () => onHover(null),
        }}
      />
      <Marker
        position={cell.center}
        icon={markerIcon}
        eventHandlers={{
          mouseover: () => onHover(cell.h3Index),
          mouseout: () => onHover(null),
        }}
      >
        <Tooltip>
          <div className="space-y-1 min-w-[180px]">
            {cell.siteName && (
              <div className="font-semibold text-sm text-stone-900">
                {cell.siteName}
              </div>
            )}
            {cell.dateRange && (
              <div className="text-xs text-stone-600">
                {formatDateRange(cell.dateRange.earliest, cell.dateRange.latest)}
              </div>
            )}
            <div className="text-xs text-stone-500">
              {cell.recordings.length} recording{cell.recordings.length !== 1 ? "s" : ""}
            </div>
          </div>
        </Tooltip>
        <Popup>
          <div className="max-w-xs">
            {cell.siteName && (
              <div className="font-bold text-base mb-1 text-stone-900">
                {cell.siteName}
              </div>
            )}
            {cell.dateRange && (
              <div className="text-sm text-stone-600 mb-3 pb-2 border-b border-stone-200">
                {formatDateRange(cell.dateRange.earliest, cell.dateRange.latest)}
              </div>
            )}
            <div className="font-semibold mb-2">
              {cell.recordings.length} recording
              {cell.recordings.length !== 1 ? "s" : ""}
            </div>
            <div className="text-xs text-stone-500 mb-2 flex gap-3">
              <span className="text-emerald-600">
                Public: {cell.publicCount}
              </span>
              {cell.restrictedCount > 0 && (
                <span className="text-amber-600">
                  Restricted: {cell.restrictedCount}
                </span>
              )}
            </div>
            <div className="max-h-48 overflow-y-auto space-y-2">
              {cell.recordings.slice(0, 10).map((recording) => (
                <div
                  key={recording.uuid}
                  className="text-xs border-b border-stone-200 pb-2 last:border-0"
                >
                  <div className="font-mono truncate">{recording.path}</div>
                  {recording.dataset && (
                    <div className="flex items-center gap-1 mt-1">
                      <Link
                        href={`/datasets/${recording.dataset.uuid}/`}
                        className="text-emerald-600 hover:underline"
                      >
                        {recording.dataset.name}
                      </Link>
                      <VisibilityBadge
                        visibility={recording.dataset.visibility}
                      />
                    </div>
                  )}
                  {recording.date && (
                    <div className="text-stone-500">
                      {new Date(recording.date).toLocaleDateString()}
                    </div>
                  )}
                </div>
              ))}
              {cell.recordings.length > 10 && (
                <div className="text-xs text-stone-500">
                  +{cell.recordings.length - 10} more
                </div>
              )}
            </div>
          </div>
        </Popup>
      </Marker>
    </Fragment>
  );
});

const MapView = memo(function MapView({
  recordings,
  drawnShape,
  isLoading,
}: MapViewProps) {
  const [highlightedCell, setHighlightedCell] = useState<string | null>(null);

  const cells = useMemo(() => aggregateByH3(recordings), [recordings]);

  const handleHover = useCallback((h3Index: string | null) => {
    setHighlightedCell(h3Index);
  }, []);

  if (isLoading) {
    return (
      <div className="h-[500px] rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-100 dark:bg-stone-800 flex items-center justify-center">
        <div className="text-stone-500 dark:text-stone-400">Loading map...</div>
      </div>
    );
  }

  return (
    <div className="rounded-lg overflow-hidden border border-stone-200 dark:border-stone-700">
      <MapContainer
        center={DEFAULT_MAP_CENTER}
        zoom={DEFAULT_MAP_ZOOM}
        scrollWheelZoom={true}
        style={{ height: 500 }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        <DrawnShapeLayer shape={drawnShape} />
        <FitBounds cells={cells} drawnShape={drawnShape} />

        {cells.map((cell) => (
          <H3HexCell
            key={cell.h3Index}
            cell={cell}
            isHighlighted={highlightedCell === cell.h3Index}
            onHover={handleHover}
          />
        ))}
      </MapContainer>
    </div>
  );
});

export default MapView;
