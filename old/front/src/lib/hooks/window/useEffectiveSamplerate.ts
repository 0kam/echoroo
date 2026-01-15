import { useMemo } from "react";

import type { AudioSettings } from "@/lib/types";

/**
 * Calculate effective samplerate based on audio resampling settings.
 * If resampling is enabled, returns the target samplerate, otherwise returns the original samplerate.
 */
export default function useEffectiveSamplerate(
  originalSamplerate: number,
  audioSettings?: AudioSettings,
): number {
  return useMemo(() => {
    if (!audioSettings?.resample) return originalSamplerate;
    return audioSettings.samplerate ?? originalSamplerate;
  }, [audioSettings?.resample, audioSettings?.samplerate, originalSamplerate]);
}
