"use client";

import { Fragment, useMemo } from "react";
import {
  MapContainer,
  Marker,
  Polygon,
  TileLayer,
  Tooltip,
} from "react-leaflet";

import MapViewport from "@/lib/components/maps/MapViewport";
import type { DatasetRecordingSite } from "@/lib/types";
import {
  DEFAULT_MAP_CENTER,
  DEFAULT_MAP_ZOOM,
  getH3BoundaryForLeaflet,
  getH3CenterForLeaflet,
} from "@/lib/utils/h3";
import { getMarkerIcon } from "@/lib/utils/leafletIcons";

export default function DatasetSitesMap({
  sites,
}: {
  sites: DatasetRecordingSite[];
}) {
  const activeSites = useMemo(
    () => sites.filter((site) => Boolean(site.h3_index)),
    [sites],
  );

  const initialCenter = useMemo<[number, number]>(() => {
    if (activeSites.length === 0) {
      return DEFAULT_MAP_CENTER;
    }
    const firstSite = activeSites[0]!;
    return getH3CenterForLeaflet(firstSite.h3_index!);
  }, [activeSites]);

  if (activeSites.length === 0) {
    return null;
  }

  const mapCenter = useMemo(
    () => ({ lat: initialCenter[0], lng: initialCenter[1] }),
    [initialCenter],
  );
  const mapZoom = activeSites.length > 1 ? 6 : 8;

  return (
    <div className="rounded-lg overflow-hidden border border-stone-200 dark:border-stone-700">
      <MapContainer
        center={mapCenter}
        zoom={DEFAULT_MAP_ZOOM}
        scrollWheelZoom={false}
        style={{ height: 256 }}
      >
        <MapViewport center={mapCenter} zoom={mapZoom} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {activeSites.map((site) => {
          const h3Index = site.h3_index!;
          const boundary = getH3BoundaryForLeaflet(h3Index);
          const center = getH3CenterForLeaflet(h3Index);
          const key = `${h3Index}-${site.latitude}-${site.longitude}`;

          return (
            <Fragment key={key}>
              <Polygon
                positions={boundary}
                pathOptions={{
                  color: "#2563eb",
                  weight: 2,
                  fillOpacity: 0.18,
                }}
              >
                <Tooltip sticky>
                  <div className="space-y-1">
                    <div className="font-semibold text-sm">
                      {site.label ?? "Recording site"}
                    </div>
                    <div className="text-xs text-stone-500">
                      {site.recording_count} recording
                      {site.recording_count !== 1 ? "s" : ""}
                    </div>
                  </div>
                </Tooltip>
              </Polygon>
              <Marker position={center} icon={getMarkerIcon("blue")}>
                <Tooltip>
                  <div className="space-y-1">
                    <div className="font-semibold text-sm">
                      {site.label ?? "Recording site"}
                    </div>
                    <div className="text-xs text-stone-500">
                      {site.recording_count} recording
                      {site.recording_count !== 1 ? "s" : ""}
                    </div>
                  </div>
                </Tooltip>
              </Marker>
            </Fragment>
          );
        })}
      </MapContainer>
    </div>
  );
}
