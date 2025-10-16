import { useCallback, useEffect, useRef, useState } from "react";

import type { SpectrogramSettingsInterface } from "@/lib/hooks/settings/useSpectrogramSettings";
import type { ViewportController } from "@/lib/types";

export default function useTimeScaleControl({
  viewport,
  spectrogramSettings,
  playbackSpeed = 1,
}: {
  viewport: ViewportController;
  spectrogramSettings: SpectrogramSettingsInterface;
  playbackSpeed?: number;
}) {
  const target = spectrogramSettings.settings.time_scale ?? 1;
  const [preview, setPreview] = useState(target);

  // 基準となるviewportの時間幅を保持（1倍の時の状態）
  const baseTimeRangeRef = useRef<number | null>(null);
  const isInitializedRef = useRef(false);
  const previousSpeedRef = useRef(playbackSpeed);

  // 初期化：baseTimeRangeを設定
  useEffect(() => {
    if (!isInitializedRef.current && viewport.viewport) {
      const range = viewport.viewport.time.max - viewport.viewport.time.min;
      baseTimeRangeRef.current = range;
      isInitializedRef.current = true;
    }
  }, [viewport.viewport]);

  // 再生速度が変わった時にviewportを調整
  useEffect(() => {
    if (!baseTimeRangeRef.current || !viewport.viewport) return;
    if (previousSpeedRef.current === playbackSpeed) return;

    previousSpeedRef.current = playbackSpeed;

    // 再生速度に応じてviewportの時間幅を調整
    // 速度が速い（>1）= 時間軸を伸ばす、速度が遅い（<1）= 時間軸を縮める
    const effectiveScale = (target > 0 ? target : 1) / playbackSpeed;
    const newTimeRange = baseTimeRangeRef.current / effectiveScale;
    const center = (viewport.viewport.time.min + viewport.viewport.time.max) / 2;

    viewport.set({
      time: {
        min: center - newTimeRange / 2,
        max: center + newTimeRange / 2,
      },
      freq: viewport.viewport.freq,
    });
  }, [playbackSpeed, target, viewport]);

  useEffect(() => {
    const nextValue = target > 0 ? target : 1;
    if (preview === nextValue) return;

    setPreview(nextValue);

    if (!baseTimeRangeRef.current || !viewport.viewport) return;

    // 基準となる時間幅をtime_scaleと再生速度で調整
    const effectiveScale = nextValue / playbackSpeed;
    const newTimeRange = baseTimeRangeRef.current / effectiveScale;
    const center = (viewport.viewport.time.min + viewport.viewport.time.max) / 2;

    viewport.set({
      time: {
        min: center - newTimeRange / 2,
        max: center + newTimeRange / 2,
      },
      freq: viewport.viewport.freq,
    });
  }, [target, viewport, preview, playbackSpeed]);

  const handlePreviewChange = useCallback(
    (next: number) => {
      if (next <= 0 || !baseTimeRangeRef.current || !viewport.viewport) return;

      setPreview(next);

      // 基準となる時間幅をtime_scaleと再生速度で調整
      const effectiveScale = next / playbackSpeed;
      const newTimeRange = baseTimeRangeRef.current / effectiveScale;
      const center = (viewport.viewport.time.min + viewport.viewport.time.max) / 2;

      viewport.set({
        time: {
          min: center - newTimeRange / 2,
          max: center + newTimeRange / 2,
        },
        freq: viewport.viewport.freq,
      });
    },
    [viewport, playbackSpeed],
  );

  const handleCommit = useCallback(
    (next: number) => {
      if (next <= 0) return;
      spectrogramSettings.dispatch({ type: "setTimeScale", timeScale: next });
    },
    [spectrogramSettings],
  );

  return {
    value: preview,
    onPreviewChange: handlePreviewChange,
    onCommit: handleCommit,
  };
}
