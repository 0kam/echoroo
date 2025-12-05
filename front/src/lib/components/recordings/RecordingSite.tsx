"use client";

import { useMemo } from "react";
import { cellToLatLng, isValidCell } from "h3-js";
import { LocationIcon } from "@/lib/components/icons";
import Tooltip from "@/lib/components/ui/Tooltip";

import type { Recording } from "@/lib/types";

function formatCoordinates(lat: number, lng: number): string {
  const latDir = lat >= 0 ? "N" : "S";
  const lngDir = lng >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(4)}${latDir}, ${Math.abs(lng).toFixed(4)}${lngDir}`;
}

export default function RecordingSite({
  recording,
}: {
  recording: Recording;
}) {
  const location = useMemo(() => {
    // Try h3_index first (primary)
    if (recording.h3_index && isValidCell(recording.h3_index)) {
      const [lat, lng] = cellToLatLng(recording.h3_index);
      return { lat, lng, source: "site" as const };
    }
    // Fall back to legacy lat/lng
    if (recording.latitude != null && recording.longitude != null) {
      return {
        lat: recording.latitude,
        lng: recording.longitude,
        source: "legacy" as const,
      };
    }
    return null;
  }, [recording.h3_index, recording.latitude, recording.longitude]);

  if (location == null) {
    return (
      <div className="inline-flex items-center gap-1 text-stone-400 dark:text-stone-600">
        <LocationIcon className="w-5 h-5" />
        <span className="text-sm">No location</span>
      </div>
    );
  }

  const tooltipContent = (
    <div className="space-y-1 text-xs">
      <div className="font-medium">
        {location.source === "site" ? "Location (from site)" : "Location (legacy)"}
      </div>
      {recording.h3_index && (
        <div className="font-mono text-stone-500">{recording.h3_index}</div>
      )}
    </div>
  );

  return (
    <Tooltip tooltip={tooltipContent}>
      <div className="inline-flex items-center gap-1">
        <LocationIcon className="w-5 h-5 text-stone-500" />
        <span>{formatCoordinates(location.lat, location.lng)}</span>
      </div>
    </Tooltip>
  );
}
