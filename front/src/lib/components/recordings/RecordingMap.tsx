import dynamic from "next/dynamic";
import { useMemo } from "react";
import { cellToLatLng, isValidCell } from "h3-js";

import { MapIcon } from "@/lib/components/icons";
import Card from "@/lib/components/ui/Card";

import type { Recording } from "@/lib/types";

// NOTE: The use of dynamic imports is necessary to avoid importing the leaflet
// library on the server side as it uses the `window` object which is not
// available on the server.
const Map = dynamic(() => import("@/lib/components/maps/Map"), { ssr: false });
const Marker = dynamic(() => import("@/lib/components/maps/DraggableMarker"), {
  ssr: false,
});

export default function RecordingMap({
  recording: { latitude, longitude, h3_index },
}: {
  recording: Recording;
}) {
  // Calculate location from h3_index if direct lat/lon not available
  const location = useMemo(() => {
    // Prioritize direct lat/lon
    if (latitude != null && longitude != null) {
      return { lat: latitude, lng: longitude };
    }

    // Fallback to h3_index
    if (h3_index && isValidCell(h3_index)) {
      try {
        const [h3Lat, h3Lng] = cellToLatLng(h3_index);
        return { lat: h3Lat, lng: h3Lng };
      } catch {
        // Invalid h3_index, return null
        return null;
      }
    }

    return null;
  }, [latitude, longitude, h3_index]);

  const hasLocation = location != null;

  return (
    <Card>
      <div className="flex flex-row justify-center items-center">
        <MapIcon className="inline-block mr-1 w-5 h-5 text-stone-500" />
        Recorded at
      </div>
      {!hasLocation ? (
        <div className="text-sm text-stone-400 dark:text-stone-600">
          No location provided.
        </div>
      ) : (
        <div className="relative">
          <Map
            className="h-64"
            center={{
              lat: location.lat,
              lng: location.lng,
            }}
            scrollWheelZoom={true}
            zoom={14}
          >
            <Marker
              draggable={false}
              updateOnChange
              center={{
                lat: location.lat,
                lng: location.lng,
              }}
            />
          </Map>
        </div>
      )}
    </Card>
  );
}
