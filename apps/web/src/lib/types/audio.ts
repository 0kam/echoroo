/**
 * Type definitions for spectrogram and audio playback system.
 */

// ============================================
// Constants
// ============================================

export const COLORMAPS = [
  'gray',
  'viridis',
  'magma',
  'inferno',
  'plasma',
  'cividis',
  'cool',
  'cubehelix',
  'twilight',
] as const;

export const WINDOWS = [
  'hann',
  'hamming',
  'boxcar',
  'triang',
  'blackman',
  'bartlett',
  'flattop',
  'parzen',
  'bohman',
  'blackmanharris',
  'nuttall',
  'barthann',
] as const;

export type Colormap = (typeof COLORMAPS)[number];
export type WindowFunction = (typeof WINDOWS)[number];

/** Minimum dB value allowed */
export const MIN_DB = -140;
/** Default minimum dB for display */
export const DEFAULT_MIN_DB = -80;
/** Default maximum dB for display */
export const DEFAULT_MAX_DB = 0;

export const DEFAULT_WINDOW_SIZE = 0.01;
export const DEFAULT_OVERLAP = 0.5;
export const DEFAULT_WINDOW: WindowFunction = 'hann';
export const DEFAULT_COLORMAP: Colormap = 'twilight';
export const DEFAULT_HEIGHT = 400;
export const DEFAULT_FILTER_ORDER = 4;

export const SCALE_MIN = 1.0;
export const SCALE_MAX = 10.0;
export const SCALE_STEP = 0.1;

export const MIN_CANVAS_HEIGHT = 200;
export const MAX_CANVAS_HEIGHT = 1200;
export const CANVAS_HEIGHT_STEP = 20;

export const MIN_SAMPLERATE = 4000;
export const MAX_SAMPLERATE = 500000;

export const LOWEST_PLAYBACK_SAMPLERATE = 8000;
export const HIGHEST_PLAYBACK_SAMPLERATE = 96000;

/** Fixed chunk duration in seconds */
export const SPECTROGRAM_CHUNK_DURATION = 5.0;
/** Buffer windows to add to each chunk */
export const SPECTROGRAM_CHUNK_BUFFER = 10;

// ============================================
// Interval and Window Types
// ============================================

/** A numeric interval with min and max bounds */
export interface Interval {
  min: number;
  max: number;
}

/** A 2D window representing time and frequency ranges */
export interface SpectrogramWindow {
  time: Interval;
  freq: Interval;
}

/** A position in spectrogram space (time + frequency) */
export interface SpectrogramPosition {
  time: number;
  freq: number;
}

// ============================================
// Interaction Mode
// ============================================

export type InteractionMode = 'idle' | 'panning' | 'zooming';

// ============================================
// Spectrogram Settings
// ============================================

export interface SpectrogramSettings {
  /** STFT window size in seconds */
  window_size: number;
  /** Overlap fraction between consecutive windows (0-1) */
  overlap: number;
  /** Window function type */
  window: WindowFunction;
  /** Canvas height in pixels */
  height: number;
  /** Whether to clamp amplitude values */
  clamp: boolean;
  /** Minimum dB value for display */
  min_dB: number;
  /** Maximum dB value for display */
  max_dB: number;
  /** Whether to normalize the spectrogram */
  normalize: boolean;
  /** Whether to apply PCEN normalization */
  pcen: boolean;
  /** Color map name */
  cmap: Colormap;
  /** Time axis scale factor (1.0-10.0) */
  time_scale: number;
  /** Frequency axis scale factor (1.0-10.0) */
  freq_scale: number;
}

export const DEFAULT_SPECTROGRAM_SETTINGS: SpectrogramSettings = {
  window_size: DEFAULT_WINDOW_SIZE,
  overlap: DEFAULT_OVERLAP,
  window: DEFAULT_WINDOW,
  height: DEFAULT_HEIGHT,
  clamp: false,
  min_dB: DEFAULT_MIN_DB,
  max_dB: DEFAULT_MAX_DB,
  normalize: true,
  pcen: false,
  cmap: DEFAULT_COLORMAP,
  time_scale: 1.0,
  freq_scale: 1.0,
};

// ============================================
// Audio Settings
// ============================================

export interface AudioSettings {
  /** Playback speed multiplier */
  speed: number;
  /** Whether to resample the audio */
  resample: boolean;
  /** Target sample rate for resampling (null = no resampling) */
  samplerate: number | null;
  /** Low frequency cut (highpass filter, Hz) */
  low_freq: number | null;
  /** High frequency cut (lowpass filter, Hz) */
  high_freq: number | null;
  /** Filter order */
  filter_order: number;
  /** Audio channel to use */
  channel: number;
}

export const DEFAULT_AUDIO_SETTINGS: AudioSettings = {
  speed: 1,
  resample: false,
  samplerate: null,
  low_freq: null,
  high_freq: null,
  filter_order: DEFAULT_FILTER_ORDER,
  channel: 0,
};

// ============================================
// Speed Options
// ============================================

export interface SpeedOption {
  label: string;
  value: number;
}

export const ALL_SPEED_OPTIONS: SpeedOption[] = [
  { label: '0.1x', value: 0.1 },
  { label: '0.25x', value: 0.25 },
  { label: '0.5x', value: 0.5 },
  { label: '0.75x', value: 0.75 },
  { label: '1x', value: 1 },
  { label: '1.2x', value: 1.2 },
  { label: '1.5x', value: 1.5 },
  { label: '1.75x', value: 1.75 },
  { label: '2x', value: 2 },
  { label: '3x', value: 3 },
];

/** Get speed options valid for the given sample rate */
export function getSpeedOptions(samplerate: number): SpeedOption[] {
  return ALL_SPEED_OPTIONS.filter((option) => {
    const effectiveRate = samplerate * option.value;
    return (
      effectiveRate >= LOWEST_PLAYBACK_SAMPLERATE &&
      effectiveRate <= HIGHEST_PLAYBACK_SAMPLERATE
    );
  });
}

// ============================================
// Chunk / Segment Types
// ============================================

export interface SpectrogramChunk {
  index: number;
  /** The actual time interval this chunk represents */
  interval: Interval;
  /** The buffered time interval used for fetching (includes overlap) */
  buffer: Interval;
  isLoading: boolean;
  isReady: boolean;
  isError: boolean;
  /** Number of load attempts that have failed so far */
  retryCount: number;
}

// ============================================
// Viewport Controller
// ============================================

export interface ViewportController {
  /** Current viewport window */
  viewport: SpectrogramWindow;
  /** Full recording bounds */
  bounds: SpectrogramWindow;
  /** Set the viewport to a specific window */
  set(window: SpectrogramWindow): void;
  /** Shift the viewport by time/freq amounts */
  shift(by: { time?: number; freq?: number }): void;
  /** Expand the viewport by time/freq amounts */
  expand(by: { time?: number; freq?: number }): void;
  /** Center the viewport on a time/freq position */
  centerOn(pos: { time?: number; freq?: number }): void;
  /** Zoom toward a specific position by a factor */
  zoomToPosition(args: { position: SpectrogramPosition; factor: number }): void;
  /** Save current viewport to history stack */
  save(): void;
  /** Return to previous viewport */
  back(): void;
  /** Reset to initial viewport */
  reset(): void;
}

// ============================================
// Audio Controller
// ============================================

export interface AudioController {
  currentTime: number;
  duration: number;
  isPlaying: boolean;
  loop: boolean;
  volume: number;
  play(): void;
  pause(): void;
  seek(time: number): void;
  setVolume(volume: number): void;
  toggleLoop(): void;
  togglePlay(): void;
}
