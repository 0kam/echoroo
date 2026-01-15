import useAxisScaleControl from "@/lib/hooks/spectrogram/useAxisScaleControl";

import type { SpectrogramSettingsInterface } from "@/lib/hooks/settings/useSpectrogramSettings";
import type { ViewportController } from "@/lib/types";

/**
 * Hook for controlling frequency axis scale in the spectrogram viewport.
 * Uses bounds-based scaling where scale=1 shows full frequency range.
 */
export default function useFreqScaleControl({
  viewport,
  spectrogramSettings,
}: {
  viewport: ViewportController;
  spectrogramSettings: SpectrogramSettingsInterface;
}) {
  return useAxisScaleControl({
    viewport,
    spectrogramSettings,
    axis: "freq",
    settingKey: "freq_scale",
    actionType: "setFreqScale",
    getOtherAxis: (vp) => vp.viewport?.time ?? { min: 0, max: 0 },
  });
}
