/**
 * Viewport utility functions for spectrogram window management.
 * Ported from the original React implementation.
 */

import type { Interval, SpectrogramWindow, SpectrogramPosition } from '$lib/types/audio';

const MIN_WINDOW_BANDWIDTH = 0.1;
const MIN_WINDOW_DURATION = 0.001;

/** Compute the intersection of two intervals, or null if no overlap */
export function intersectIntervals(a: Interval, b: Interval): Interval | null {
  const min = Math.max(a.min, b.min);
  const max = Math.min(a.max, b.max);
  if (min > max) return null;
  return { min, max };
}

/** Compute the intersection of two spectrogram windows, or null if no overlap */
export function intersectWindows(
  w1: SpectrogramWindow,
  w2: SpectrogramWindow
): SpectrogramWindow | null {
  const time = intersectIntervals(w1.time, w2.time);
  const freq = intersectIntervals(w1.freq, w2.freq);
  if (!time || !freq) return null;
  return { time, freq };
}

/** Scale an interval by a factor around its center */
export function scaleInterval(interval: Interval, factor: number): Interval {
  const duration = interval.max - interval.min;
  const center = (interval.max + interval.min) / 2;
  return {
    min: center - (duration / 2) * factor,
    max: center + (duration / 2) * factor,
  };
}

/** Adjust a spectrogram window to stay within bounds */
export function adjustWindowToBounds(
  window: SpectrogramWindow,
  bounds: SpectrogramWindow
): SpectrogramWindow {
  let duration = window.time.max - window.time.min;
  let bandwidth = window.freq.max - window.freq.min;

  duration = Math.max(duration, MIN_WINDOW_DURATION);
  bandwidth = Math.max(bandwidth, MIN_WINDOW_BANDWIDTH);

  const centerTime = (window.time.max + window.time.min) / 2;
  const centerFreq = (window.freq.max + window.freq.min) / 2;

  const adjustedCenterTime = Math.min(
    Math.max(centerTime, bounds.time.min + duration / 2),
    bounds.time.max - duration / 2
  );

  const adjustedCenterFreq = Math.min(
    Math.max(centerFreq, bounds.freq.min + bandwidth / 2),
    bounds.freq.max - bandwidth / 2
  );

  const adjusted: SpectrogramWindow = {
    time: {
      min: adjustedCenterTime - duration / 2,
      max: adjustedCenterTime + duration / 2,
    },
    freq: {
      min: adjustedCenterFreq - bandwidth / 2,
      max: adjustedCenterFreq + bandwidth / 2,
    },
  };

  return intersectWindows(adjusted, bounds) ?? adjusted;
}

/** Shift a spectrogram window by absolute amounts */
export function shiftWindow(
  window: SpectrogramWindow,
  by: { time?: number; freq?: number }
): SpectrogramWindow {
  return {
    time: {
      min: window.time.min + (by.time ?? 0),
      max: window.time.max + (by.time ?? 0),
    },
    freq: {
      min: window.freq.min + (by.freq ?? 0),
      max: window.freq.max + (by.freq ?? 0),
    },
  };
}

/** Expand a spectrogram window by absolute amounts on each side */
export function expandWindow(
  window: SpectrogramWindow,
  by: { time?: number; freq?: number }
): SpectrogramWindow {
  return {
    time: {
      min: window.time.min - (by.time ?? 0),
      max: window.time.max + (by.time ?? 0),
    },
    freq: {
      min: window.freq.min - (by.freq ?? 0),
      max: window.freq.max + (by.freq ?? 0),
    },
  };
}

/** Center a window on a given time/freq position */
export function centerWindowOn(
  window: SpectrogramWindow,
  pos: { time?: number; freq?: number }
): SpectrogramWindow {
  const width = window.time.max - window.time.min;
  const height = window.freq.max - window.freq.min;
  const timeMin = pos.time != null ? pos.time - width / 2 : window.time.min;
  const timeMax = pos.time != null ? pos.time + width / 2 : window.time.max;
  const freqMin = pos.freq != null ? pos.freq - height / 2 : window.freq.min;
  const freqMax = pos.freq != null ? pos.freq + height / 2 : window.freq.max;
  return {
    time: { min: timeMin, max: timeMax },
    freq: { min: freqMin, max: freqMax },
  };
}

/** Zoom toward a position by a factor (factor > 1 = zoom out, < 1 = zoom in) */
export function zoomWindowToPosition(
  window: SpectrogramWindow,
  position: SpectrogramPosition,
  factor: number
): SpectrogramWindow {
  return {
    time: {
      min: factor * window.time.min + (1 - factor) * position.time,
      max: factor * window.time.max + (1 - factor) * position.time,
    },
    freq: {
      min: factor * window.freq.min + (1 - factor) * position.freq,
      max: factor * window.freq.max + (1 - factor) * position.freq,
    },
  };
}

/**
 * Get the CSS position of a viewport indicator within a bounding container.
 * Returns left/top/width/height as pixel values.
 */
export function getViewportPosition({
  width,
  height,
  viewport,
  bounds,
}: {
  width: number;
  height: number;
  viewport: SpectrogramWindow;
  bounds: SpectrogramWindow;
}): { left: number; top: number; width: number; height: number } {
  const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

  const bottom =
    (bounds.freq.max - viewport.freq.min) / (bounds.freq.max - bounds.freq.min);
  const top =
    (bounds.freq.max - viewport.freq.max) / (bounds.freq.max - bounds.freq.min);
  const left =
    (viewport.time.min - bounds.time.min) / (bounds.time.max - bounds.time.min);
  const right =
    (viewport.time.max - bounds.time.min) / (bounds.time.max - bounds.time.min);

  return {
    top: clamp(top * height, 0, height),
    left: clamp(left * width, 0, width),
    height: clamp((bottom - top) * height, 0, height),
    width: clamp((right - left) * width, 0, width),
  };
}

/**
 * Apply a mouse-wheel gesture to a spectrogram viewport.
 *
 * Mirrors the dataset spectrogram navigation (no mode gate):
 *   - plain scroll      → pan (shift time/freq)
 *   - Ctrl + scroll     → expand/contract the window
 *   - Alt + scroll      → zoom toward the cursor position
 *
 * Shift swaps the deltaX/deltaY axes so a horizontal trackpad gesture maps to
 * the same action as a vertical wheel. The result is always clamped to the
 * supplied `bounds`. Extracted from `useSpectrogramInteraction.handleWheel`
 * so both the dataset viewer and the annotation overlay share one wheel model.
 *
 * @param e          Wheel deltas + modifier flags (a subset of `WheelEvent`).
 * @param viewport   The current spectrogram window.
 * @param bounds     The clip/recording bounds to clamp against.
 * @param cursorPos  Cursor position in spectrogram coords (zoom anchor).
 * @param canvasWidth Live canvas width in CSS px (drives the zoom factor scale).
 */
export function applyWheelToViewport(
  e: { deltaX: number; deltaY: number; altKey: boolean; ctrlKey: boolean; shiftKey: boolean },
  viewport: SpectrogramWindow,
  bounds: SpectrogramWindow,
  cursorPos: SpectrogramPosition,
  canvasWidth: number
): SpectrogramWindow {
  const timeFrac = (viewport.time.max - viewport.time.min) * 0.05;
  const freqFrac = (viewport.freq.max - viewport.freq.min) * 0.05;

  const deltaX = e.deltaX;
  const deltaY = e.deltaY;

  if (e.altKey) {
    // Zoom toward cursor position.
    const factor = 1 + 4 * timeFrac * (e.shiftKey ? deltaX : deltaY) / (canvasWidth * timeFrac);
    return adjustWindowToBounds(
      zoomWindowToPosition(viewport, cursorPos, Math.max(0.1, factor)),
      bounds
    );
  }

  if (e.ctrlKey) {
    // Expand/contract viewport.
    return adjustWindowToBounds(
      expandWindow(viewport, {
        time: timeFrac * (e.shiftKey ? deltaX : deltaY) * 0.1,
        freq: freqFrac * (e.shiftKey ? deltaY : deltaX) * 0.1,
      }),
      bounds
    );
  }

  // Scroll time/frequency (pan).
  return adjustWindowToBounds(
    shiftWindow(viewport, {
      time: timeFrac * (e.shiftKey ? deltaY : deltaX) * 0.1,
      freq: -freqFrac * (e.shiftKey ? deltaX : deltaY) * 0.1,
    }),
    bounds
  );
}

/** Convert canvas pixel coordinates to spectrogram time/freq position */
export function pixelsToPosition(
  x: number,
  y: number,
  canvasWidth: number,
  canvasHeight: number,
  viewport: SpectrogramWindow
): SpectrogramPosition {
  const { time, freq } = viewport;
  const t = time.min + (x / canvasWidth) * (time.max - time.min);
  const f = freq.max - (y / canvasHeight) * (freq.max - freq.min);
  return { time: t, freq: f };
}

/** Convert a time value to a canvas X pixel coordinate */
export function timeToPixel(
  time: number,
  canvasWidth: number,
  viewport: SpectrogramWindow
): number {
  const { min, max } = viewport.time;
  return (canvasWidth * (time - min)) / (max - min);
}

/** Convert a frequency value to a canvas Y pixel coordinate */
export function freqToPixel(
  freq: number,
  canvasHeight: number,
  viewport: SpectrogramWindow
): number {
  const { min, max } = viewport.freq;
  return (canvasHeight * (max - freq)) / (max - min);
}

/**
 * Get the initial viewport for a recording.
 * Shows the first N seconds at full frequency range.
 */
export function getInitialViewingWindow({
  startTime,
  endTime,
  samplerate,
}: {
  startTime: number;
  endTime: number;
  samplerate: number;
}): SpectrogramWindow {
  const DEFAULT_INITIAL_DURATION = 20;
  const duration = Math.min(endTime - startTime, DEFAULT_INITIAL_DURATION);
  return {
    time: { min: startTime, max: startTime + duration },
    freq: { min: 0, max: samplerate / 2 },
  };
}

/**
 * Calculate spectrogram chunk intervals for lazy loading.
 */
export function calculateChunkIntervals(
  duration: number,
  windowSize: number,
  overlap: number,
  chunkDuration: number,
  chunkBuffer: number
): Array<{ index: number; interval: Interval; buffer: Interval }> {
  const windowWidth = (1 - overlap) * windowSize;
  const bufferSize = (chunkBuffer - 1) * windowWidth + windowSize;
  const count = Math.ceil(duration / chunkDuration);

  return Array.from({ length: count }, (_, i) => ({
    index: i,
    interval: {
      min: i * chunkDuration,
      max: Math.min((i + 1) * chunkDuration, duration),
    },
    buffer: {
      min: i * chunkDuration - bufferSize,
      max: (i + 1) * chunkDuration + bufferSize,
    },
  }));
}
