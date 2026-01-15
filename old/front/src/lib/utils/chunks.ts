import type { Chunk } from "@/lib/types";

/**
 * The size in pixels of a spectrogram chunk.
 */
export const SPECTROGRAM_CHUNK_SIZE = 512 * 512;

/**
 * The buffer in number of spectrogram windows to add to each chunk.
 */
export const SPECTROGRAM_CHUNK_BUFFER = 10;

/**
 * The target duration for each spectrogram chunk in seconds.
 * This is kept constant to ensure consistent time resolution regardless of window size.
 */
export const SPECTROGRAM_CHUNK_DURATION = 5.0;

/**
 * Calculates the time intervals for spectrogram chunks based on recording and
 * settings.
 */
export function calculateSpectrogramChunkIntervals({
  duration,
  windowSize,
  overlap,
  samplerate: _samplerate,
  chunkSize: _chunkSize = SPECTROGRAM_CHUNK_SIZE,
  chunkBuffer = SPECTROGRAM_CHUNK_BUFFER,
}: {
  /** The duration of the recording in seconds. */
  duration: number;
  /** The duration of each STFT window in seconds. */
  windowSize: number;
  /** The overlap fraction between consecutive windows. */
  overlap: number;
  /** The audio sample rate in Hz. (kept for API compatibility) */
  samplerate: number;
  /** The size of each spectrogram chunk in pixels. (kept for API compatibility) */
  chunkSize?: number;
  /** The overlap fraction between consecutive chunks. */
  chunkBuffer?: number;
}): Chunk[] {
  // Use fixed time duration instead of calculating from chunkSize
  // This ensures consistent time resolution regardless of window size settings
  const chunkDuration = SPECTROGRAM_CHUNK_DURATION;
  const windowWidth = (1 - overlap) * windowSize;
  const buffer = (chunkBuffer - 1) * windowWidth + windowSize;

  return Array.from({ length: Math.ceil(duration / chunkDuration) }, (_, i) => {
    return {
      interval: {
        min: i * chunkDuration,
        max: (i + 1) * chunkDuration,
      },
      buffer: {
        min: i * chunkDuration - buffer,
        max: (i + 1) * chunkDuration + buffer,
      },
    };
  });
}
