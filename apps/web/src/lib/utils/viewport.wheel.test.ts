/**
 * Unit tests for `applyWheelToViewport` — the shared scroll-wheel navigation
 * math used by BOTH the dataset spectrogram viewer and the annotation overlay.
 *
 * The three gestures (plain scroll = pan, Ctrl+scroll = expand, Alt+scroll =
 * zoom-to-cursor) must produce the same window transform on either surface, and
 * every result must stay clamped within the supplied bounds.
 */
import { describe, it, expect } from 'vitest';
import { applyWheelToViewport } from './viewport';
import type { SpectrogramWindow } from '$lib/types/audio';

const CANVAS_WIDTH = 800;

const BOUNDS: SpectrogramWindow = {
  time: { min: 0, max: 60 },
  freq: { min: 0, max: 24000 },
};

/** A mid-clip viewport: [10s, 30s] over the lower half of the frequency band. */
const VIEWPORT: SpectrogramWindow = {
  time: { min: 10, max: 30 },
  freq: { min: 0, max: 12000 },
};

/** Cursor at the centre of the viewport (zoom anchor). */
const CURSOR = { time: 20, freq: 6000 };

function wheel(over: Partial<WheelEvent>): {
  deltaX: number;
  deltaY: number;
  altKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
} {
  return {
    deltaX: 0,
    deltaY: 0,
    altKey: false,
    ctrlKey: false,
    shiftKey: false,
    ...over,
  };
}

describe('applyWheelToViewport', () => {
  it('plain scroll pans the time window (positive deltaX shifts right)', () => {
    const next = applyWheelToViewport(
      wheel({ deltaX: 100 }),
      VIEWPORT,
      BOUNDS,
      CURSOR,
      CANVAS_WIDTH,
    );
    // Window duration is preserved (a pan, not a zoom).
    expect(next.time.max - next.time.min).toBeCloseTo(20);
    // Positive deltaX shifts the window forward in time.
    expect(next.time.min).toBeGreaterThan(VIEWPORT.time.min);
  });

  it('Alt+scroll zooms toward the cursor (deltaY < 0 zooms in)', () => {
    const next = applyWheelToViewport(
      wheel({ deltaY: -100, altKey: true }),
      VIEWPORT,
      BOUNDS,
      CURSOR,
      CANVAS_WIDTH,
    );
    const beforeDuration = VIEWPORT.time.max - VIEWPORT.time.min;
    const afterDuration = next.time.max - next.time.min;
    // Zooming in shrinks the visible window.
    expect(afterDuration).toBeLessThan(beforeDuration);
    // Anchored on the cursor (centre here), so the centre is preserved.
    expect((next.time.min + next.time.max) / 2).toBeCloseTo(CURSOR.time, 1);
  });

  it('Ctrl+scroll expands/contracts the window without panning the centre', () => {
    const next = applyWheelToViewport(
      wheel({ deltaY: 100, ctrlKey: true }),
      VIEWPORT,
      BOUNDS,
      CURSOR,
      CANVAS_WIDTH,
    );
    const beforeDuration = VIEWPORT.time.max - VIEWPORT.time.min;
    const afterDuration = next.time.max - next.time.min;
    // Positive delta expands the window (wider view).
    expect(afterDuration).toBeGreaterThan(beforeDuration);
    // Expansion is symmetric about the current centre.
    expect((next.time.min + next.time.max) / 2).toBeCloseTo(20, 1);
  });

  it('always clamps the result within the supplied bounds', () => {
    // A huge positive pan must not push the window past the clip end.
    const next = applyWheelToViewport(
      wheel({ deltaX: 1e6 }),
      VIEWPORT,
      BOUNDS,
      CURSOR,
      CANVAS_WIDTH,
    );
    expect(next.time.min).toBeGreaterThanOrEqual(BOUNDS.time.min);
    expect(next.time.max).toBeLessThanOrEqual(BOUNDS.time.max + 1e-6);
    expect(next.freq.min).toBeGreaterThanOrEqual(BOUNDS.freq.min);
    expect(next.freq.max).toBeLessThanOrEqual(BOUNDS.freq.max + 1e-6);
  });
});
