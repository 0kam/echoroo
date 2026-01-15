import { useMemo } from "react";

import useEffectiveSamplerate from "@/lib/hooks/window/useEffectiveSamplerate";
import useFrequencyRangeReset from "@/lib/hooks/window/useFrequencyRangeReset";
import useViewport from "@/lib/hooks/window/useViewport";

import { DEFAULT_SPECTROGRAM_SETTINGS } from "@/lib/constants";
import type { AudioSettings, Recording, SpectrogramSettings } from "@/lib/types";
import {
  adjustWindowToBounds,
  getInitialViewingWindow,
} from "@/lib/utils/windows";

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
  const effectiveSamplerate = useEffectiveSamplerate(
    recording.samplerate,
    audioSettings,
  );

  const bounds = useMemo(
    () => ({
      time: { min: startTime, max: endTime || recording.duration },
      freq: { min: 0, max: effectiveSamplerate / 2 },
    }),
    [recording.duration, effectiveSamplerate, startTime, endTime],
  );

  const initial = useMemo(
    () => {
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
          min: timeCenter - timeRange / (2 * Math.max(timeScale, 1e-6)),
          max: timeCenter + timeRange / (2 * Math.max(timeScale, 1e-6)),
        },
        freq: {
          min: Math.max(
            freqCenter - freqRange / (2 * Math.max(freqScale, 1e-6)),
            bounds.freq.min,
          ),
          max: Math.min(
            freqCenter + freqRange / (2 * Math.max(freqScale, 1e-6)),
            bounds.freq.max,
          ),
        },
      };

      return adjustWindowToBounds(
        {
          time: {
            min: Math.max(scaledWindow.time.min, bounds.time.min),
            max: Math.min(scaledWindow.time.max, bounds.time.max),
          },
          freq: {
            min: Math.max(scaledWindow.freq.min, bounds.freq.min),
            max: Math.min(scaledWindow.freq.max, bounds.freq.max),
          },
        },
        bounds,
      );
    },
    [
      bounds,
      effectiveSamplerate,
      spectrogramSettings.window_size,
      spectrogramSettings.overlap,
      spectrogramSettings.time_scale,
      spectrogramSettings.freq_scale,
    ],
  );

  const viewport = useViewport({
    initial,
    bounds,
  });

  useFrequencyRangeReset(
    viewport,
    effectiveSamplerate,
    spectrogramSettings.freq_scale ?? 1,
  );

  return viewport;
}
