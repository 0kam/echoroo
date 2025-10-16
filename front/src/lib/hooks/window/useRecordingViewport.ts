import { useEffect, useMemo } from "react";

import useViewport from "@/lib/hooks/window/useViewport";

import { DEFAULT_SPECTROGRAM_SETTINGS } from "@/lib/constants";
import type { AudioSettings, Recording, SpectrogramSettings } from "@/lib/types";
import { getInitialViewingWindow } from "@/lib/utils/windows";

export default function useRecordingViewport({
  recording,
  startTime = 0,
  endTime,
  spectrogramSettings = DEFAULT_SPECTROGRAM_SETTINGS,
  audioSettings,
}: {
  recording: Recording;
  startTime?: number;
  endTime?: number;
  spectrogramSettings?: SpectrogramSettings;
  audioSettings?: AudioSettings;
}) {
  // Calculate effective samplerate based on resampling settings
  const effectiveSamplerate = useMemo(() => {
    if (!audioSettings?.resample) return recording.samplerate;
    return audioSettings.samplerate ?? recording.samplerate;
  }, [audioSettings?.resample, audioSettings?.samplerate, recording.samplerate]);

  const bounds = useMemo(
    () => ({
      time: { min: startTime, max: endTime || recording.duration },
      freq: { min: 0, max: effectiveSamplerate / 2 },
    }),
    [recording.duration, effectiveSamplerate, startTime, endTime],
  );

  const initial = useMemo(
    () =>
      getInitialViewingWindow({
        startTime: bounds.time.min,
        endTime: bounds.time.max,
        samplerate: effectiveSamplerate,
        windowSize: spectrogramSettings.window_size,
        overlap: spectrogramSettings.overlap,
      }),
    [
      bounds.time.min,
      bounds.time.max,
      effectiveSamplerate,
      spectrogramSettings.window_size,
      spectrogramSettings.overlap,
    ],
  );

  const viewport = useViewport({
    initial,
    bounds,
  });

  // Reset frequency range when effective samplerate changes
  useEffect(() => {
    viewport.setFrequencyInterval({ min: 0, max: effectiveSamplerate / 2 });
  }, [effectiveSamplerate, viewport.setFrequencyInterval]);

  return viewport;
}
