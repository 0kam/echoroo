import { useEffect, useMemo } from "react";

import useEffectiveSamplerate from "@/lib/hooks/window/useEffectiveSamplerate";
import useFrequencyRangeReset from "@/lib/hooks/window/useFrequencyRangeReset";
import useViewport from "@/lib/hooks/window/useViewport";

import type { AudioSettings, Recording, SoundEvent } from "@/lib/types";
import { getGeometryViewingWindow } from "@/lib/utils/windows";

export default function useSoundEventViewport({
  soundEvent,
  recording,
  audioSettings,
}: {
  soundEvent: SoundEvent;
  recording: Recording;
  audioSettings?: AudioSettings;
}) {
  const effectiveSamplerate = useEffectiveSamplerate(
    recording.samplerate,
    audioSettings,
  );

  const bounds = useMemo(
    () =>
      getGeometryViewingWindow({
        geometry: soundEvent.geometry,
        recording,
        timeBuffer: 0.2,
        effectiveSamplerate,
      }),
    [soundEvent.geometry, recording, effectiveSamplerate],
  );

  const initial = useMemo(
    () =>
      getGeometryViewingWindow({
        geometry: soundEvent.geometry,
        recording,
        timeBuffer: 0.1,
        freqBuffer: null,
        effectiveSamplerate,
      }),
    [soundEvent.geometry, recording, effectiveSamplerate],
  );

  const viewport = useViewport({
    initial,
    bounds,
  });

  const { set: setViewport } = viewport;

  useEffect(() => {
    setViewport(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [soundEvent.uuid, setViewport]);

  useFrequencyRangeReset(viewport, effectiveSamplerate);

  return viewport;
}
