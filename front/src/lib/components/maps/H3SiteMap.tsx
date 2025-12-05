"use client";

import L from "leaflet";
import { Fragment, useMemo } from "react";
import {
  MapContainer,
  Marker,
  Polygon,
  TileLayer,
  Tooltip,
} from "react-leaflet";

import MapViewport from "@/lib/components/maps/MapViewport";
import {
  DEFAULT_MAP_CENTER,
  DEFAULT_MAP_ZOOM,
  getH3BoundaryForLeaflet,
  getH3CenterForLeaflet,
  isValidH3Index,
} from "@/lib/utils/h3";

type SiteSummary = {
  site_id: string;
  site_name?: string | null;
  h3_index: string | null;
};

// Inline marker icon creation to avoid SSR issues with separate module
const MARKER_ICON_BASE_URL =
  "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img";

const iconCache = new Map<string, L.Icon>();

function getMarkerIcon(color: "blue" | "green"): L.Icon {
  const cached = iconCache.get(color);
  if (cached) return cached;

  const icon = new L.Icon({
    iconUrl: `${MARKER_ICON_BASE_URL}/marker-icon-2x-${color}.png`,
    shadowUrl: `${MARKER_ICON_BASE_URL}/marker-shadow.png`,
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
    shadowSize: [41, 41],
  });

  iconCache.set(color, icon);
  return icon;
}

export default function H3SiteMap({
  sites,
  selectedSiteId,
  onSelect,
  height = 320,
}: {
  sites: SiteSummary[];
  selectedSiteId?: string | null;
  onSelect?: (siteId: string) => void;
  height?: number;
}) {
  const activeSites = useMemo(
    () =>
      sites.filter((site) => isValidH3Index(site.h3_index)) as Array<
        SiteSummary & { h3_index: string }
      >,
    [sites],
  );

  const initialCenter = useMemo<[number, number]>(() => {
    if (activeSites.length === 0) {
      return DEFAULT_MAP_CENTER;
    }
    if (selectedSiteId) {
      const selected = activeSites.find(
        (site) => site.site_id === selectedSiteId,
      );
      if (selected) {
        return getH3CenterForLeaflet(selected.h3_index);
      }
    }
    return getH3CenterForLeaflet(activeSites[0].h3_index);
  }, [activeSites, selectedSiteId]);

  const mapZoom = useMemo(() => activeSites.length ? 6 : DEFAULT_MAP_ZOOM, [activeSites.length]);

  return (
    <div className="rounded-lg overflow-hidden border border-stone-200 dark:border-stone-700">
      <MapContainer
        center={{ lat: initialCenter[0], lng: initialCenter[1] }}
        zoom={DEFAULT_MAP_ZOOM}
        scrollWheelZoom={false}
        style={{ height }}
      >
        <MapViewport
          center={initialCenter}
          zoom={mapZoom}
        />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {activeSites.map((site) => {
          const boundary = getH3BoundaryForLeaflet(site.h3_index);
          const center = getH3CenterForLeaflet(site.h3_index);
          const isSelected = site.site_id === selectedSiteId;

          return (
            <Fragment key={site.site_id}>
              <Polygon
                key={`polygon-${site.site_id}`}
                positions={boundary}
                pathOptions={{
                  color: isSelected ? "#10b981" : "#2563eb",
                  weight: isSelected ? 3 : 2,
                  fillOpacity: isSelected ? 0.35 : 0.18,
                }}
                eventHandlers={
                  onSelect
                    ? {
                      click: () => onSelect(site.site_id),
                    }
                    : undefined
                }
              >
                <Tooltip sticky>
                  <div className="space-y-1">
                    <div className="font-semibold text-sm">
                      {site.site_name ?? site.site_id}
                    </div>
                    <div className="font-mono text-xs text-stone-200">
                      {site.site_id}
                    </div>
                  </div>
                </Tooltip>
              </Polygon>
              <Marker
                key={`marker-${site.site_id}`}
                position={center}
                icon={getMarkerIcon(isSelected ? "green" : "blue")}
                eventHandlers={
                  onSelect
                    ? {
                      click: () => onSelect(site.site_id),
                    }
                    : undefined
                }
              >
                <Tooltip>
                  <div className="space-y-1">
                    <div className="font-semibold text-sm">
                      {site.site_name ?? site.site_id}
                    </div>
                    <div className="font-mono text-xs text-stone-200">
                      {site.site_id}
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
