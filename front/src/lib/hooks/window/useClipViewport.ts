import { useEffect, useMemo } from "react";

import useViewport from "@/lib/hooks/window/useViewport";

import { DEFAULT_SPECTROGRAM_SETTINGS } from "@/lib/constants";
import type { AudioSettings, Clip, SpectrogramSettings } from "@/lib/types";
import { getInitialViewingWindow } from "@/lib/utils/windows";

export default function useClipViewport({
  clip,
  spectrogramSettings = DEFAULT_SPECTROGRAM_SETTINGS,
  audioSettings,
}: {
  clip: Clip;
  spectrogramSettings?: SpectrogramSettings;
  audioSettings?: AudioSettings;
}) {
  // Calculate effective samplerate based on resampling settings
  const effectiveSamplerate = useMemo(() => {
    if (!audioSettings?.resample) return clip.recording.samplerate;
    return audioSettings.samplerate ?? clip.recording.samplerate;
  }, [audioSettings?.resample, audioSettings?.samplerate, clip.recording.samplerate]);

  const bounds = useMemo(
    () => ({
      time: { min: clip.start_time, max: clip.end_time },
      freq: { min: 0, max: effectiveSamplerate / 2 },
    }),
    [effectiveSamplerate, clip.start_time, clip.end_time],
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
      bounds,
      effectiveSamplerate,
      spectrogramSettings.window_size,
      spectrogramSettings.overlap,
    ],
  );

  const viewport = useViewport({
    initial,
    bounds,
  });

  const { set: setViewport } = viewport;

  useEffect(() => {
    setViewport(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clip.uuid, setViewport]);

  // Reset frequency range when effective samplerate changes
  useEffect(() => {
    viewport.setFrequencyInterval({ min: 0, max: effectiveSamplerate / 2 });
  }, [effectiveSamplerate, viewport.setFrequencyInterval]);

  return viewport;
}
