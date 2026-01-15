import { useEffect, useMemo } from "react";

import useEffectiveSamplerate from "@/lib/hooks/window/useEffectiveSamplerate";
import useFrequencyRangeReset from "@/lib/hooks/window/useFrequencyRangeReset";
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
  const effectiveSamplerate = useEffectiveSamplerate(
    clip.recording.samplerate,
    audioSettings,
  );

  const bounds = useMemo(
    () => ({
      time: { min: clip.start_time, max: clip.end_time },
      freq: { min: 0, max: effectiveSamplerate / 2 },
    }),
    [effectiveSamplerate, clip.start_time, clip.end_time],
  );

  const initial = useMemo(() => {
    const baseWindow = getInitialViewingWindow({
      startTime: bounds.time.min,
      endTime: bounds.time.max,
      samplerate: effectiveSamplerate,
      windowSize: spectrogramSettings.window_size,
      overlap: spectrogramSettings.overlap,
    });

    const timeScale = spectrogramSettings.time_scale ?? 1;
    const freqScale = spectrogramSettings.freq_scale ?? 1;

    const timeRange = baseWindow.time.max - baseWindow.time.min;
    const freqRange = baseWindow.freq.max - baseWindow.freq.min;
    const timeCenter =
      (baseWindow.time.max + baseWindow.time.min) / 2;
    const freqCenter =
      (baseWindow.freq.max + baseWindow.freq.min) / 2;

    const scaledWindow = {
      time: {
        min: Math.max(
          bounds.time.min,
          timeCenter - timeRange / (2 * Math.max(timeScale, 1e-6)),
        ),
        max: Math.min(
          bounds.time.max,
          timeCenter + timeRange / (2 * Math.max(timeScale, 1e-6)),
        ),
      },
      freq: {
        min: Math.max(
          bounds.freq.min,
          freqCenter - freqRange / (2 * Math.max(freqScale, 1e-6)),
        ),
        max: Math.min(
          bounds.freq.max,
          freqCenter + freqRange / (2 * Math.max(freqScale, 1e-6)),
        ),
      },
    };

    return scaledWindow;
  }, [
    bounds,
    effectiveSamplerate,
    spectrogramSettings.window_size,
    spectrogramSettings.overlap,
    spectrogramSettings.time_scale,
    spectrogramSettings.freq_scale,
  ]);

  const viewport = useViewport({
    initial,
    bounds,
  });

  const { set: setViewport } = viewport;

  useEffect(() => {
    setViewport(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clip.uuid, setViewport]);

  useFrequencyRangeReset(
    viewport,
    effectiveSamplerate,
    spectrogramSettings.freq_scale ?? 1,
  );

  return viewport;
}
