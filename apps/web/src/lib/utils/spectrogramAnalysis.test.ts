import { describe, it, expect } from 'vitest';
import {
  fft,
  hannWindow,
  computeSpectrogram,
  warmColormap,
} from './spectrogramAnalysis';

describe('fft', () => {
  it('is a no-op for length <= 1', () => {
    const real = new Float32Array([3]);
    const imag = new Float32Array([0]);
    fft(real, imag);
    expect(real[0]).toBe(3);
    expect(imag[0]).toBe(0);
  });

  it('transforms a constant (DC) signal into a single non-zero bin', () => {
    const n = 8;
    const real = new Float32Array(n).fill(1);
    const imag = new Float32Array(n);
    fft(real, imag);
    // DC bin equals the sum of all samples; all other bins ~0.
    expect(real[0]).toBeCloseTo(n, 5);
    for (let k = 1; k < n; k++) {
      expect(Math.hypot(real[k]!, imag[k]!)).toBeCloseTo(0, 5);
    }
  });

  it('produces a peak at the expected bin for a pure sine wave', () => {
    const n = 64;
    const cyclesPerWindow = 4; // peak should land at bin 4 (and its mirror n-4)
    const real = new Float32Array(n);
    const imag = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      real[i] = Math.sin((2 * Math.PI * cyclesPerWindow * i) / n);
    }
    fft(real, imag);

    const mags: number[] = [];
    for (let k = 0; k < n; k++) {
      mags.push(Math.hypot(real[k]!, imag[k]!));
    }
    // Find the peak bin within the lower (non-mirrored) half.
    let peakBin = 0;
    let peakMag = -Infinity;
    for (let k = 0; k < n / 2; k++) {
      if (mags[k]! > peakMag) {
        peakMag = mags[k]!;
        peakBin = k;
      }
    }
    expect(peakBin).toBe(cyclesPerWindow);
    // The mirror bin (n - cyclesPerWindow) should match in magnitude.
    expect(mags[n - cyclesPerWindow]!).toBeCloseTo(peakMag, 4);
  });
});

describe('hannWindow', () => {
  it('has zero (within float precision) endpoints', () => {
    const win = hannWindow(16);
    expect(win[0]).toBeCloseTo(0, 6);
    expect(win[win.length - 1]).toBeCloseTo(0, 6);
  });

  it('is symmetric about its center', () => {
    const length = 17;
    const win = hannWindow(length);
    for (let i = 0; i < length; i++) {
      expect(win[i]).toBeCloseTo(win[length - 1 - i]!, 6);
    }
  });

  it('reaches its maximum of 1 at the center of an odd-length window', () => {
    const length = 9;
    const win = hannWindow(length);
    const center = (length - 1) / 2;
    expect(win[center]).toBeCloseTo(1, 6);
    for (let i = 0; i < length; i++) {
      expect(win[i]!).toBeLessThanOrEqual(1 + 1e-6);
      expect(win[i]!).toBeGreaterThanOrEqual(0 - 1e-6);
    }
  });
});

describe('computeSpectrogram', () => {
  it('returns columns sized fftSize/2+1 with the expected frame count', () => {
    const fftSize = 64;
    const hopSize = 16;
    const samples = new Float32Array(256);
    for (let i = 0; i < samples.length; i++) {
      samples[i] = Math.sin((2 * Math.PI * 8 * i) / fftSize);
    }
    const cols = computeSpectrogram(samples, fftSize, hopSize);
    const expectedFrames = Math.floor((samples.length - fftSize) / hopSize) + 1;
    expect(cols.length).toBe(expectedFrames);
    for (const col of cols) {
      expect(col.length).toBe(fftSize / 2 + 1);
    }
  });

  it('puts the strongest energy at the bin matching a pure sine input', () => {
    const fftSize = 256;
    const hopSize = 64;
    const cyclesPerWindow = 16; // expected peak bin
    const samples = new Float32Array(1024);
    for (let i = 0; i < samples.length; i++) {
      samples[i] = Math.sin((2 * Math.PI * cyclesPerWindow * i) / fftSize);
    }
    const cols = computeSpectrogram(samples, fftSize, hopSize);
    // Inspect an interior frame to avoid window edge effects.
    const col = cols[Math.floor(cols.length / 2)]!;
    let peakBin = 0;
    let peakVal = -Infinity;
    for (let k = 0; k < col.length; k++) {
      if (col[k]! > peakVal) {
        peakVal = col[k]!;
        peakBin = k;
      }
    }
    expect(peakBin).toBe(cyclesPerWindow);
  });

  it('always returns at least one frame even for short input', () => {
    const cols = computeSpectrogram(new Float32Array(4), 64, 16);
    expect(cols.length).toBe(1);
    expect(cols[0]!.length).toBe(64 / 2 + 1);
  });
});

describe('warmColormap', () => {
  it('clamps inputs below 0 to the darkest color', () => {
    expect(warmColormap(-5)).toEqual(warmColormap(0));
  });

  it('clamps inputs above 1 to the brightest color', () => {
    expect(warmColormap(2)).toEqual(warmColormap(1));
  });

  it('returns the ramp endpoints exactly', () => {
    // t = 0 -> dark brown (#1a0a00)
    expect(warmColormap(0)).toEqual([26, 10, 0]);
    // t = 1 -> white (#FFFFFF)
    expect(warmColormap(1)).toEqual([255, 255, 255]);
  });

  it('produces RGB channels within the valid 0-255 range across the ramp', () => {
    for (let i = 0; i <= 100; i++) {
      const [r, g, b] = warmColormap(i / 100);
      for (const channel of [r, g, b]) {
        expect(channel).toBeGreaterThanOrEqual(0);
        expect(channel).toBeLessThanOrEqual(255);
        expect(Number.isInteger(channel)).toBe(true);
      }
    }
  });

  it('increases red channel monotonically through the warm-up portion', () => {
    // Red rises from brown to bright orange over [0, 0.5) then stays at 255.
    expect(warmColormap(0.1)[0]).toBeLessThan(warmColormap(0.4)[0]);
    expect(warmColormap(0.6)[0]).toBe(255);
  });
});
