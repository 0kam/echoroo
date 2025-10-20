import { useCallback, useEffect, useRef, useState } from "react";

import type { SpectrogramSettingsInterface } from "@/lib/hooks/settings/useSpectrogramSettings";
import type { ViewportController } from "@/lib/types";

const DEFAULT_TIME_WINDOW = 20;

/**
 * Hook for controlling time axis scale in the spectrogram viewport.
 * Uses ref-based scaling to maintain a base time range that adapts to playback speed.
 * The effective scale combines time_scale and playback speed.
 */
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

  const baseTimeRangeRef = useRef<number | null>(null);
  const previousSpeedRef = useRef(playbackSpeed);
  const lastAppliedRef = useRef<{ scale: number; speed: number } | null>(null);

  const applyScale = useCallback(
    (scaleValue: number) => {
      const baseRange = baseTimeRangeRef.current;
      if (!baseRange || !viewport.viewport) return;

      const last = lastAppliedRef.current;
      if (last && last.scale === scaleValue && last.speed === playbackSpeed) {
        return;
      }

      const effectiveScale = scaleValue / playbackSpeed;
      const newTimeRange = baseRange / effectiveScale;
      const center =
        (viewport.viewport.time.min + viewport.viewport.time.max) / 2;

      viewport.set({
        time: {
          min: center - newTimeRange / 2,
          max: center + newTimeRange / 2,
        },
        freq: viewport.viewport.freq,
      });

      lastAppliedRef.current = { scale: scaleValue, speed: playbackSpeed };
    },
    [viewport, playbackSpeed],
  );

  // Initialize and update base time range from viewport bounds
  useEffect(() => {
    if (!viewport.viewport) return;

    const boundsRange =
      viewport.bounds.time.max - viewport.bounds.time.min;
    const candidateRange =
      boundsRange > 0
        ? Math.min(DEFAULT_TIME_WINDOW, boundsRange)
        : DEFAULT_TIME_WINDOW;
    const nextBaseRange =
      candidateRange > 0 ? candidateRange : DEFAULT_TIME_WINDOW;

    if (
      baseTimeRangeRef.current == null ||
      Math.abs(baseTimeRangeRef.current - nextBaseRange) >
        Number.EPSILON
    ) {
      baseTimeRangeRef.current = nextBaseRange;
      lastAppliedRef.current = null;
    }

    const nextValue = target > 0 ? target : 1;
    setPreview((prev) => (prev === nextValue ? prev : nextValue));
    applyScale(nextValue);
  }, [
    viewport.viewport,
    viewport.bounds.time.min,
    viewport.bounds.time.max,
    target,
    applyScale,
  ]);

  // Handle playback speed changes
  useEffect(() => {
    if (previousSpeedRef.current === playbackSpeed) return;
    previousSpeedRef.current = playbackSpeed;

    if (!baseTimeRangeRef.current || !viewport.viewport) return;

    const nextValue = target > 0 ? target : 1;
    applyScale(nextValue);
  }, [playbackSpeed, target, viewport.viewport, applyScale]);

  // Handle scale setting changes
  useEffect(() => {
    const nextValue = target > 0 ? target : 1;
    setPreview((prev) => (prev === nextValue ? prev : nextValue));

    if (!baseTimeRangeRef.current || !viewport.viewport) return;

    applyScale(nextValue);
  }, [target, viewport.viewport, applyScale]);

  const handlePreviewChange = useCallback(
    (next: number) => {
      if (next <= 0) return;
      setPreview(next);
      applyScale(next);
    },
    [applyScale],
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
