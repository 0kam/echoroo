import { useCallback, useEffect, useRef, useState } from "react";

import type { SpectrogramSettingsInterface } from "@/lib/hooks/settings/useSpectrogramSettings";
import type { Interval, ViewportController } from "@/lib/types";

type Axis = "time" | "freq";

interface AxisScaleControlConfig {
  viewport: ViewportController;
  spectrogramSettings: SpectrogramSettingsInterface;
  axis: Axis;
  settingKey: "time_scale" | "freq_scale";
  actionType: "setTimeScale" | "setFreqScale";
  getOtherAxis: (viewport: ViewportController) => Interval;
}

/**
 * Generic hook for controlling viewport scale on a specific axis (time or freq).
 * Extracts common logic from useTimeScaleControl and useFreqScaleControl.
 */
export default function useAxisScaleControl({
  viewport,
  spectrogramSettings,
  axis,
  settingKey,
  actionType,
  getOtherAxis,
}: AxisScaleControlConfig) {
  const target = spectrogramSettings.settings[settingKey] ?? 1;
  const [preview, setPreview] = useState(target);
  const lastAppliedRef = useRef<number | null>(null);

  const updateViewport = useCallback(
    (scaleValue: number) => {
      if (!viewport.viewport || !viewport.bounds) return;
      if (lastAppliedRef.current === scaleValue) return;
      lastAppliedRef.current = scaleValue;

      const baseRange = viewport.bounds[axis].max - viewport.bounds[axis].min;
      const newRange = baseRange / scaleValue;
      const current = viewport.viewport[axis];
      const center = (current.min + current.max) / 2;

      const newInterval: Interval = {
        min: Math.max(center - newRange / 2, viewport.bounds[axis].min),
        max: Math.min(center + newRange / 2, viewport.bounds[axis].max),
      };

      const otherAxisInterval = getOtherAxis(viewport);

      if (axis === "time") {
        viewport.set({
          time: newInterval,
          freq: otherAxisInterval,
        });
      } else {
        viewport.set({
          time: otherAxisInterval,
          freq: newInterval,
        });
      }
    },
    [viewport, axis, getOtherAxis],
  );

  useEffect(() => {
    const nextValue = target > 0 ? target : 1;
    setPreview((prev) => (prev === nextValue ? prev : nextValue));
    if (lastAppliedRef.current === nextValue) return;
    updateViewport(nextValue);
  }, [target, updateViewport]);

  const handlePreviewChange = useCallback(
    (next: number) => {
      if (next <= 0) return;
      setPreview(next);
      updateViewport(next);
    },
    [updateViewport],
  );

  const handleCommit = useCallback(
    (next: number) => {
      if (next <= 0) return;

      if (actionType === "setTimeScale") {
        spectrogramSettings.dispatch({
          type: "setTimeScale",
          timeScale: next,
        });
      } else {
        spectrogramSettings.dispatch({
          type: "setFreqScale",
          freqScale: next,
        });
      }
    },
    [spectrogramSettings, actionType],
  );

  return {
    value: preview,
    onPreviewChange: handlePreviewChange,
    onCommit: handleCommit,
  };
}
