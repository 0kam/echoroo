import classNames from "classnames";
import { DivIcon } from "leaflet";
import { useMemo } from "react";
import { MapContainer } from "react-leaflet/MapContainer";
import { Marker } from "react-leaflet/Marker";
import { Popup } from "react-leaflet/Popup";
import { TileLayer } from "react-leaflet/TileLayer";

import * as icons from "@/lib/components/icons";
import Tag from "@/lib/components/tags/Tag";

import type * as types from "@/lib/types";
import { type Color, getTagClassNames, getTagKey } from "@/lib/utils/tags";

const DEFAULT_COLOR: Color = { color: "stone", level: 3 };

export default function RecordingMap({
  tagColorFn,
  recordings,
  ...props
}: {
  recordings: types.Recording[];
  onClickRecording?: (recording: types.Recording) => void;
  tagColorFn?: (tag: types.Tag) => Color;
  colorBy?: string | null;
}) {
  const recordingsWithLocation = useMemo(() => {
    return recordings.filter(
      (recording) => recording.latitude != null && recording.longitude != null,
    );
  }, [recordings]);

  const position = useMemo(() => {
    if (recordingsWithLocation.length === 0) {
      return { lat: 0, lng: 0 };
    }
    let latitude = 0;
    let longitude = 0;
    for (let recording of recordingsWithLocation) {
      latitude += recording.latitude as number;
      longitude += recording.longitude as number;
    }
    latitude /= recordingsWithLocation.length;
    longitude /= recordingsWithLocation.length;
    return { lat: latitude, lng: longitude };
  }, [recordingsWithLocation]);

  return (
    <MapContainer
      center={position}
      zoom={6}
      scrollWheelZoom={true}
      style={{ height: "600px" }}
    >
      <TileLayer
        attribution="Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ"
        url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
      />
      {recordingsWithLocation.map((recording) => (
        <RecordingMarker
          key={recording.uuid}
          recording={recording}
          colorBy={props.colorBy}
          onClick={() => props.onClickRecording?.(recording)}
          tagColorFn={tagColorFn}
        />
      ))}
    </MapContainer>
  );
}

function RecordingMarker({
  recording,
  onClick,
  colorBy,
  tagColorFn,
}: {
  recording: types.Recording;
  onClick?: () => void;
  colorBy?: string | null;
  tagColorFn?: (tag: types.Tag) => Color;
}) {
  const icon = useMemo(() => {
    const color = getMarkerColor({ recording, colorBy, tagColorFn });
    return new DivIcon({
      className: color,
      iconSize: [20, 20],
    });
  }, [recording, colorBy, tagColorFn]);

  return (
    <Marker
      key={recording.uuid}
      eventHandlers={{
        click: onClick,
        mouseover: (event) => event.target.openPopup(),
        mouseout: (event) => event.target.closePopup(),
      }}
      icon={icon}
      position={{
        lat: recording.latitude as number,
        lng: recording.longitude as number,
      }}
    >
      <RecordingPopup recording={recording} tagColorFn={tagColorFn} />
    </Marker>
  );
}

function getMarkerColor({
  recording,
  colorBy = null,
  tagColorFn,
}: {
  recording: types.Recording;
  colorBy?: string | null;
  tagColorFn?: (tag: types.Tag) => Color;
}) {
  const common = "border-2 rounded-full w-4 h-4 drop-shadow-md";

  if (colorBy == null) {
    return classNames(common, "bg-emerald-200 border-emerald-500");
  }

  const tag = recording.tags?.find((tag) => tag.key === colorBy);

  if (tag == null) {
    return classNames(common, "bg-stone-200 border-stone-500");
  }

  let { color, level } = tagColorFn ? tagColorFn(tag) : DEFAULT_COLOR;
  let names = getTagClassNames(color, level);
  return classNames(names.background, names.border, common);
}

function RecordingPopup({
  recording,
  tagColorFn,
}: {
  recording: types.Recording;
  tagColorFn?: (tag: types.Tag) => Color;
}) {
  return (
    <Popup>
      <div className="flex flex-col gap-2">
        <div>{recording.path}</div>
        <RecordingAttribute
          field="duration"
          value={`${recording.duration} s`}
        />
        <RecordingAttribute
          field="samplerate"
          value={`${recording.samplerate} Hz`}
        />
        {recording.date && (
          <RecordingAttribute
            field="date"
            value={recording.date.toLocaleString()}
          />
        )}
        {recording.time && (
          <RecordingAttribute field="time" value={recording.time} />
        )}
        <div className="flex flex-row gap-2">
          <icons.TagsIcon className="w-4 h-4 text-stone-500" />
          <div className="flex flex-col gap-2">
            {recording.tags?.map((tag) => (
              <Tag
                key={getTagKey(tag)}
                tag={tag}
                {...(tagColorFn ? tagColorFn(tag) : DEFAULT_COLOR)}
              />
            ))}
          </div>
        </div>
      </div>
    </Popup>
  );
}

function RecordingAttribute({
  field,
  value,
}: {
  field: string;
  value: string;
}) {
  return (
    <div className="flex flex-row gap-2">
      <span className="text-stone-500">{field}</span>
      {value}
    </div>
  );
}
