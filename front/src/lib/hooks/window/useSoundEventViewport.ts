import { useEffect, useMemo } from "react";

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
  // Calculate effective samplerate based on resampling settings
  const effectiveSamplerate = useMemo(() => {
    if (!audioSettings?.resample) return recording.samplerate;
    return audioSettings.samplerate ?? recording.samplerate;
  }, [audioSettings?.resample, audioSettings?.samplerate, recording.samplerate]);

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

  // Reset frequency range when effective samplerate changes
  useEffect(() => {
    viewport.setFrequencyInterval({ min: 0, max: effectiveSamplerate / 2 });
  }, [effectiveSamplerate, viewport.setFrequencyInterval]);

  return viewport;
}
