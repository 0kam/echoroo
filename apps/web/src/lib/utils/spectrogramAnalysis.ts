/**
 * Shared spectrogram DSP utilities.
 *
 * Pure, framework-agnostic functions used by SpectrogramClipEditor and
 * SpectrogramViewer to compute and render STFT-based spectrograms from raw
 * PCM audio data. Extracted verbatim from the components so both share a
 * single, behavior-preserving implementation.
 */

/**
 * In-place radix-2 Cooley-Tukey FFT.
 * `real` and `imag` must have the same length, which must be a power of two.
 */
export function fft(real: Float32Array, imag: Float32Array): void {
  const n = real.length;
  if (n <= 1) return;

  // Bit reversal permutation
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) {
      j ^= bit;
    }
    j ^= bit;
    if (i < j) {
      let tmp = real[i]!;
      real[i] = real[j]!;
      real[j] = tmp;
      tmp = imag[i]!;
      imag[i] = imag[j]!;
      imag[j] = tmp;
    }
  }

  // Iterative FFT butterfly
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (2 * Math.PI) / len;
    const wReal = Math.cos(ang);
    const wImag = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let curReal = 1;
      let curImag = 0;
      for (let j = 0; j < len >> 1; j++) {
        const uReal = real[i + j]!;
        const uImag = imag[i + j]!;
        const vReal =
          real[i + j + (len >> 1)]! * curReal - imag[i + j + (len >> 1)]! * curImag;
        const vImag =
          real[i + j + (len >> 1)]! * curImag + imag[i + j + (len >> 1)]! * curReal;
        real[i + j] = uReal + vReal;
        imag[i + j] = uImag + vImag;
        real[i + j + (len >> 1)] = uReal - vReal;
        imag[i + j + (len >> 1)] = uImag - vImag;
        const newCurReal = curReal * wReal - curImag * wImag;
        curImag = curReal * wImag + curImag * wReal;
        curReal = newCurReal;
      }
    }
  }
}

/**
 * Build a Hann window of the given length.
 */
export function hannWindow(length: number): Float32Array {
  const win = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    win[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (length - 1)));
  }
  return win;
}

/**
 * Compute STFT magnitude spectrogram from mono PCM samples.
 * Returns an array of magnitude columns (one per time frame),
 * each with fftSize/2+1 frequency bins stored as log-magnitude values.
 */
export function computeSpectrogram(
  samples: Float32Array,
  fftSize: number,
  hopSize: number
): Float32Array[] {
  const win = hannWindow(fftSize);
  const numBins = fftSize / 2 + 1;
  const numFrames = Math.max(1, Math.floor((samples.length - fftSize) / hopSize) + 1);
  const columns: Float32Array[] = [];

  const real = new Float32Array(fftSize);
  const imag = new Float32Array(fftSize);

  for (let frame = 0; frame < numFrames; frame++) {
    const offset = frame * hopSize;
    real.fill(0);
    imag.fill(0);

    // Apply Hann window to the frame
    for (let i = 0; i < fftSize; i++) {
      const sampleIdx = offset + i;
      real[i] = sampleIdx < samples.length ? (samples[sampleIdx]! * win[i]!) : 0;
    }

    fft(real, imag);

    // Compute log-magnitude spectrum
    const col = new Float32Array(numBins);
    for (let k = 0; k < numBins; k++) {
      const mag = Math.sqrt(real[k]! * real[k]! + imag[k]! * imag[k]!);
      col[k] = 10 * Math.log10(mag + 1e-10);
    }
    columns.push(col);
  }

  return columns;
}

/**
 * Map a normalized intensity value (0–1) to a warm colormap RGB triple.
 * Color ramp: dark brown → deep orange → bright orange → yellow → white.
 * Inputs outside [0, 1] are clamped.
 */
export function warmColormap(t: number): [number, number, number] {
  // Clamp to [0, 1]
  t = Math.max(0, Math.min(1, t));

  if (t < 0.25) {
    // dark brown (#1a0a00) → deep orange (#7a2800)
    const s = t / 0.25;
    return [
      Math.round(26 + s * (122 - 26)),
      Math.round(10 + s * (40 - 10)),
      0,
    ];
  } else if (t < 0.5) {
    // deep orange (#7a2800) → bright orange (#FF5A00)
    const s = (t - 0.25) / 0.25;
    return [
      Math.round(122 + s * (255 - 122)),
      Math.round(40 + s * (90 - 40)),
      0,
    ];
  } else if (t < 0.75) {
    // bright orange (#FF5A00) → yellow (#FFE000)
    const s = (t - 0.5) / 0.25;
    return [255, Math.round(90 + s * (224 - 90)), 0];
  } else {
    // yellow (#FFE000) → white (#FFFFFF)
    const s = (t - 0.75) / 0.25;
    return [255, Math.round(224 + s * (255 - 224)), Math.round(s * 255)];
  }
}
