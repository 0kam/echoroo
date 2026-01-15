import { useEffect, useCallback } from "react";

import type { ViewportController } from "@/lib/types";

/**
 * Automatically reset frequency range when effective samplerate changes.
 * This ensures the viewport stays within valid bounds when resampling settings change.
 */
export default function useFrequencyRangeReset(
  viewport: ViewportController,
  effectiveSamplerate: number,
  freqScale = 1,
): void {
  const { setFrequencyInterval } = viewport;

  const setFrequencyRange = useCallback(() => {
    const maxFreq = effectiveSamplerate / 2;
    if (maxFreq <= 0) {
      setFrequencyInterval({ min: 0, max: 0 });
      return;
    }

    const scale = Math.max(freqScale, 1e-6);
    const desiredBandwidth = maxFreq / scale;
    const center = maxFreq / 2;
    const halfBandwidth = desiredBandwidth / 2;
    const min = Math.max(0, center - halfBandwidth);
    const max = Math.min(maxFreq, center + halfBandwidth);

    setFrequencyInterval({ min, max });
  }, [effectiveSamplerate, freqScale, setFrequencyInterval]);

  useEffect(() => {
    setFrequencyRange();
  }, [setFrequencyRange]);
}
