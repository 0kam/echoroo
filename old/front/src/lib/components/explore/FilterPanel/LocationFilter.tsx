"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { MapContainer, TileLayer, FeatureGroup, useMap } from "react-leaflet";
import L from "leaflet";
import type { FeatureGroup as FeatureGroupType } from "leaflet";

import "leaflet-draw/dist/leaflet.draw.css";

import Button from "@/lib/components/ui/Button";
import type { DrawnShape } from "@/app/store/explore";

type LocationFilterProps = {
  value: DrawnShape | null;
  onChange: (shape: DrawnShape | null) => void;
  height?: number;
};

const DEFAULT_CENTER: [number, number] = [35.681236, 139.767125];
const DEFAULT_ZOOM = 4;

function layerToShape(layer: L.Layer, layerType: string): DrawnShape | null {
  if (layerType === "rectangle") {
    const bounds = (layer as L.Rectangle).getBounds();
    return {
      type: "rectangle",
      bounds: [
        bounds.getWest(),
        bounds.getSouth(),
        bounds.getEast(),
        bounds.getNorth(),
      ],
    };
  }

  if (layerType === "circle") {
    const circle = layer as L.Circle;
    const center = circle.getLatLng();
    const radius = circle.getRadius();
    // Calculate approximate bounding box from circle
    const latDelta = (radius / 111320) * 1.1; // Add 10% margin
    const lngDelta = latDelta / Math.cos((center.lat * Math.PI) / 180);
    return {
      type: "circle",
      bounds: [
        center.lng - lngDelta,
        center.lat - latDelta,
        center.lng + lngDelta,
        center.lat + latDelta,
      ],
      center: [center.lat, center.lng],
      radius: radius,
    };
  }

  if (layerType === "polygon") {
    const polygon = layer as L.Polygon;
    const latlngs = polygon.getLatLngs()[0] as L.LatLng[];
    const coordinates: [number, number][] = latlngs.map((ll) => [ll.lat, ll.lng]);

    // Calculate bounding box
    const lats = coordinates.map((c) => c[0]);
    const lngs = coordinates.map((c) => c[1]);
    const bounds = [
      Math.min(...lngs),
      Math.min(...lats),
      Math.max(...lngs),
      Math.max(...lats),
    ];

    return {
      type: "polygon",
      bounds,
      coordinates,
    };
  }

  return null;
}

// Component to handle draw controls
function DrawControls({
  featureGroupRef,
  onChange,
}: {
  featureGroupRef: React.RefObject<FeatureGroupType | null>;
  onChange: (shape: DrawnShape | null) => void;
}) {
  const map = useMap();
  const drawControlRef = useRef<L.Control.Draw | null>(null);
  const eventNamesRef = useRef<{
    created: string;
    deleted: string;
    edited: string;
  } | null>(null);

  // Use ref to store latest onChange to avoid stale closures in event handlers
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    let isMounted = true;

    // Dynamically import leaflet-draw to avoid SSR issues
    import("leaflet-draw").then(() => {
      if (!isMounted || !featureGroupRef.current || drawControlRef.current) return;

      // Store event names after leaflet-draw is loaded
      eventNamesRef.current = {
        created: L.Draw.Event.CREATED,
        deleted: L.Draw.Event.DELETED,
        edited: L.Draw.Event.EDITED,
      };

      const drawControl = new L.Control.Draw({
        position: "topright",
        draw: {
          polygon: {
            allowIntersection: false,
            showArea: true,
            shapeOptions: {
              color: "#10b981",
              fillOpacity: 0.2,
            },
          },
          rectangle: {
            shapeOptions: {
              color: "#10b981",
              fillOpacity: 0.2,
            },
          },
          circle: {
            shapeOptions: {
              color: "#10b981",
              fillOpacity: 0.2,
            },
          },
          polyline: false,
          circlemarker: false,
          marker: false,
        },
        edit: {
          featureGroup: featureGroupRef.current,
          remove: true,
        },
      });

      drawControlRef.current = drawControl;
      map.addControl(drawControl);

      // Handle draw created event
      const handleCreated = (e: L.LeafletEvent) => {
        const event = e as unknown as { layer: L.Layer; layerType: string };
        const layer = event.layer;

        // Clear previous shapes
        featureGroupRef.current?.clearLayers();

        // Add new shape
        featureGroupRef.current?.addLayer(layer);

        // Convert to DrawnShape
        const shape = layerToShape(layer, event.layerType);
        onChangeRef.current(shape);
      };

      // Handle draw deleted event
      const handleDeleted = () => {
        onChangeRef.current(null);
      };

      // Handle draw edited event
      const handleEdited = (e: L.LeafletEvent) => {
        const event = e as unknown as { layers: L.LayerGroup };
        const layers = event.layers;
        layers.eachLayer((layer: L.Layer) => {
          let layerType: string = "polygon";
          if (layer instanceof L.Rectangle) {
            layerType = "rectangle";
          } else if (layer instanceof L.Circle) {
            layerType = "circle";
          }
          const shape = layerToShape(layer, layerType);
          onChangeRef.current(shape);
        });
      };

      map.on(L.Draw.Event.CREATED, handleCreated);
      map.on(L.Draw.Event.DELETED, handleDeleted);
      map.on(L.Draw.Event.EDITED, handleEdited);
    });

    return () => {
      isMounted = false;
      if (drawControlRef.current) {
        map.removeControl(drawControlRef.current);
        drawControlRef.current = null;
      }
      // Only remove event listeners if we have the event names
      if (eventNamesRef.current) {
        map.off(eventNamesRef.current.created);
        map.off(eventNamesRef.current.deleted);
        map.off(eventNamesRef.current.edited);
      }
    };
  }, [map, featureGroupRef]); // Remove onChange from deps since we use ref

  return null;
}

// Component to restore shape from state
function RestoreShape({
  shape,
  featureGroupRef,
}: {
  shape: DrawnShape | null;
  featureGroupRef: React.RefObject<FeatureGroupType | null>;
}) {
  const map = useMap();

  useEffect(() => {
    if (!featureGroupRef.current) return;

    // Clear existing layers
    featureGroupRef.current.clearLayers();

    if (!shape) return;

    let layer: L.Layer | null = null;

    if (shape.type === "rectangle") {
      const [minLon, minLat, maxLon, maxLat] = shape.bounds;
      layer = L.rectangle(
        [
          [minLat, minLon],
          [maxLat, maxLon],
        ],
        {
          color: "#10b981",
          fillOpacity: 0.2,
        },
      );
    } else if (shape.type === "circle" && shape.center && shape.radius) {
      layer = L.circle([shape.center[0], shape.center[1]], {
        radius: shape.radius,
        color: "#10b981",
        fillOpacity: 0.2,
      });
    } else if (shape.type === "polygon" && shape.coordinates) {
      layer = L.polygon(
        shape.coordinates.map(([lat, lng]) => [lat, lng]),
        {
          color: "#10b981",
          fillOpacity: 0.2,
        },
      );
    }

    if (layer) {
      featureGroupRef.current.addLayer(layer);
      // Fit map to bounds
      if (shape.bounds && shape.bounds.length === 4) {
        const [minLon, minLat, maxLon, maxLat] = shape.bounds;
        map.fitBounds([
          [minLat, minLon],
          [maxLat, maxLon],
        ]);
      }
    }
  }, [shape, featureGroupRef, map]);

  return null;
}

export default function LocationFilter({
  value,
  onChange,
  height = 500,
}: LocationFilterProps) {
  const featureGroupRef = useRef<FeatureGroupType | null>(null);
  const [isReady, setIsReady] = useState(false);

  const handleClear = useCallback(() => {
    featureGroupRef.current?.clearLayers();
    onChange(null);
  }, [onChange]);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-stone-700 dark:text-stone-300">
          Location
        </span>
        {value && (
          <Button
            mode="text"
            padding="px-2 py-1"
            className="text-xs"
            onClick={handleClear}
          >
            Clear
          </Button>
        )}
      </div>

      <div className="rounded-lg overflow-hidden border border-stone-200 dark:border-stone-700">
        <MapContainer
          center={DEFAULT_CENTER}
          zoom={DEFAULT_ZOOM}
          scrollWheelZoom={true}
          style={{ height }}
          whenReady={() => setIsReady(true)}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <FeatureGroup
            ref={featureGroupRef as React.RefObject<FeatureGroupType>}
          >
            {isReady && (
              <>
                <DrawControls
                  featureGroupRef={featureGroupRef}
                  onChange={onChange}
                />
                <RestoreShape shape={value} featureGroupRef={featureGroupRef} />
              </>
            )}
          </FeatureGroup>
        </MapContainer>
      </div>

      <p className="text-xs text-stone-500 dark:text-stone-400">
        Use the drawing tools on the map to select an area. You can draw
        rectangles, circles, or custom polygons.
      </p>
    </div>
  );
}
