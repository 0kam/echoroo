import { useCallback, useEffect, useRef, useState } from "react";

import type { SpectrogramSettingsInterface } from "@/lib/hooks/settings/useSpectrogramSettings";
import type { ViewportController } from "@/lib/types";

export default function useFreqScaleControl({
  viewport,
  spectrogramSettings,
}: {
  viewport: ViewportController;
  spectrogramSettings: SpectrogramSettingsInterface;
}) {
  const target = spectrogramSettings.settings.freq_scale ?? 1;
  const [preview, setPreview] = useState(target);

  useEffect(() => {
    const nextValue = target > 0 ? target : 1;
    if (preview === nextValue) return;

    setPreview(nextValue);

    if (!viewport.viewport || !viewport.bounds) return;

    // 基準となる周波数幅は常にboundsの最大範囲（1倍の状態）
    const baseFreqRange = viewport.bounds.freq.max - viewport.bounds.freq.min;
    // freq_scaleで割る（大きい値 = 狭い範囲 = 拡大表示）
    const newFreqRange = baseFreqRange / nextValue;
    const center = (viewport.viewport.freq.min + viewport.viewport.freq.max) / 2;

    viewport.set({
      time: viewport.viewport.time,
      freq: {
        min: Math.max(center - newFreqRange / 2, 0),
        max: Math.min(center + newFreqRange / 2, viewport.bounds.freq.max),
      },
    });
  }, [target, viewport, preview]);

  const handlePreviewChange = useCallback(
    (next: number) => {
      if (next <= 0 || !viewport.viewport || !viewport.bounds) return;

      setPreview(next);

      // 基準となる周波数幅は常にboundsの最大範囲（1倍の状態）
      const baseFreqRange = viewport.bounds.freq.max - viewport.bounds.freq.min;
      // freq_scaleで割る（大きい値 = 狭い範囲 = 拡大表示）
      const newFreqRange = baseFreqRange / next;
      const center = (viewport.viewport.freq.min + viewport.viewport.freq.max) / 2;

      viewport.set({
        time: viewport.viewport.time,
        freq: {
          min: Math.max(center - newFreqRange / 2, 0),
          max: Math.min(center + newFreqRange / 2, viewport.bounds.freq.max),
        },
      });
    },
    [viewport],
  );

  const handleCommit = useCallback(
    (next: number) => {
      if (next <= 0) return;
      spectrogramSettings.dispatch({ type: "setFreqScale", freqScale: next });
    },
    [spectrogramSettings],
  );

  return {
    value: preview,
    onPreviewChange: handlePreviewChange,
    onCommit: handleCommit,
  };
}
