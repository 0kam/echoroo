/**
 * Coordinate-math tests for the annotation-editor spectrogram parity work.
 *
 * The annotation overlay's click-to-seek and box geometry both go through
 * `pixelsToPosition` / `timeToPixel` against the LIVE viewport (not a fixed
 * clip fraction). These tests pin the round-trip and, crucially, the behaviour
 * under a zoomed/panned viewport — the exact case the old percentage-based
 * `clientXToTime` got wrong (it assumed the viewport always spanned the whole
 * clip, so seek landed at the wrong time under any zoom).
 */
import { describe, it, expect } from 'vitest';
import { pixelsToPosition, timeToPixel } from './viewport';
import type { SpectrogramWindow } from '$lib/types/audio';

const CANVAS_WIDTH = 800;
const CANVAS_HEIGHT = 400;

describe('viewport coordinate math (annotation seek + box geometry)', () => {
  it('maps pixels to time linearly across an unzoomed clip viewport', () => {
    // Viewport spans the full 10s clip; the canvas mid-point is t=5s.
    const viewport: SpectrogramWindow = {
      time: { min: 0, max: 10 },
      freq: { min: 0, max: 24000 },
    };
    expect(pixelsToPosition(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT, viewport).time).toBeCloseTo(0);
    expect(
      pixelsToPosition(CANVAS_WIDTH / 2, 0, CANVAS_WIDTH, CANVAS_HEIGHT, viewport).time,
    ).toBeCloseTo(5);
    expect(
      pixelsToPosition(CANVAS_WIDTH, 0, CANVAS_WIDTH, CANVAS_HEIGHT, viewport).time,
    ).toBeCloseTo(10);
  });

  it('respects a ZOOMED (2x) viewport — the seek-fix case', () => {
    // Viewport zoomed to the second half of the same 10s clip [5,10]. Under the
    // old percentage math, clicking the canvas centre would have produced t=5s
    // (50% of the clip). With viewport-aware math it must produce t=7.5s
    // (50% of the *viewport* window).
    const viewport: SpectrogramWindow = {
      time: { min: 5, max: 10 },
      freq: { min: 0, max: 24000 },
    };
    expect(
      pixelsToPosition(CANVAS_WIDTH / 2, 0, CANVAS_WIDTH, CANVAS_HEIGHT, viewport).time,
    ).toBeCloseTo(7.5);
    expect(pixelsToPosition(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT, viewport).time).toBeCloseTo(5);
    expect(
      pixelsToPosition(CANVAS_WIDTH, 0, CANVAS_WIDTH, CANVAS_HEIGHT, viewport).time,
    ).toBeCloseTo(10);
  });

  it('round-trips time → pixel → time under a panned/zoomed viewport', () => {
    const viewport: SpectrogramWindow = {
      time: { min: 12.3, max: 15.8 },
      freq: { min: 0, max: 48000 },
    };
    for (const t of [12.3, 13.0, 14.05, 15.8]) {
      const px = timeToPixel(t, CANVAS_WIDTH, viewport);
      const back = pixelsToPosition(px, 0, CANVAS_WIDTH, CANVAS_HEIGHT, viewport).time;
      expect(back).toBeCloseTo(t, 6);
    }
  });

  it('places a box left edge inside the canvas and beyond it when panned out', () => {
    const viewport: SpectrogramWindow = {
      time: { min: 5, max: 10 },
      freq: { min: 0, max: 24000 },
    };
    // A box at t=7.5s sits at the canvas centre.
    expect(timeToPixel(7.5, CANVAS_WIDTH, viewport)).toBeCloseTo(CANVAS_WIDTH / 2);
    // A box at t=2s (before the viewport) maps to a negative x — the overlay's
    // overflow:hidden clips it out of view rather than wrapping it.
    expect(timeToPixel(2, CANVAS_WIDTH, viewport)).toBeLessThan(0);
    // A box at t=12s (after the viewport) maps beyond the canvas width.
    expect(timeToPixel(12, CANVAS_WIDTH, viewport)).toBeGreaterThan(CANVAS_WIDTH);
  });
});
