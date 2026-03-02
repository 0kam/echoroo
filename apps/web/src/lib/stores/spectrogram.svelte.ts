/**
 * Svelte 5 rune-based store for spectrogram display settings.
 * These settings are shared across the application.
 */

import {
  DEFAULT_SPECTROGRAM_SETTINGS,
  type SpectrogramSettings,
  type Colormap,
  type WindowFunction,
  COLORMAPS,
  WINDOWS,
  MIN_DB,
  SCALE_MIN,
  SCALE_MAX,
  MIN_CANVAS_HEIGHT,
  MAX_CANVAS_HEIGHT,
} from '$lib/types/audio';

function createSpectrogramStore() {
  let settings = $state<SpectrogramSettings>({ ...DEFAULT_SPECTROGRAM_SETTINGS });

  function setWindowSize(windowSize: number) {
    if (windowSize <= 0) throw new Error('Window size must be greater than 0');
    settings.window_size = windowSize;
  }

  function setOverlap(overlap: number) {
    if (overlap <= 0 || overlap >= 1)
      throw new Error('Overlap must be between 0 and 1 (exclusive)');
    settings.overlap = overlap;
  }

  function setWindow(window: WindowFunction) {
    if (!(WINDOWS as readonly string[]).includes(window))
      throw new Error(`Invalid window type: ${window}`);
    settings.window = window;
  }

  function setColormap(cmap: Colormap) {
    if (!(COLORMAPS as readonly string[]).includes(cmap))
      throw new Error(`Invalid colormap: ${cmap}`);
    settings.cmap = cmap;
  }

  function setDBRange(min?: number, max?: number) {
    const nextMin = min ?? settings.min_dB;
    const nextMax = max ?? settings.max_dB;
    if (nextMin >= nextMax) throw new Error('min_dB must be less than max_dB');
    if (nextMin < MIN_DB) throw new Error(`min_dB must be >= ${MIN_DB}`);
    if (min !== undefined) settings.min_dB = min;
    if (max !== undefined) settings.max_dB = max;
  }

  function setHeight(height: number) {
    if (height < MIN_CANVAS_HEIGHT || height > MAX_CANVAS_HEIGHT)
      throw new Error(`Height must be between ${MIN_CANVAS_HEIGHT} and ${MAX_CANVAS_HEIGHT}`);
    settings.height = height;
  }

  function setTimeScale(timeScale: number) {
    if (timeScale < SCALE_MIN || timeScale > SCALE_MAX)
      throw new Error(`Time scale must be between ${SCALE_MIN} and ${SCALE_MAX}`);
    settings.time_scale = timeScale;
  }

  function setFreqScale(freqScale: number) {
    if (freqScale < SCALE_MIN || freqScale > SCALE_MAX)
      throw new Error(`Frequency scale must be between ${SCALE_MIN} and ${SCALE_MAX}`);
    settings.freq_scale = freqScale;
  }

  function togglePCEN() {
    settings.pcen = !settings.pcen;
  }

  function toggleNormalize() {
    settings.normalize = !settings.normalize;
  }

  function toggleClamp() {
    settings.clamp = !settings.clamp;
  }

  function setAll(newSettings: SpectrogramSettings) {
    settings = { ...newSettings };
  }

  function reset() {
    settings = { ...DEFAULT_SPECTROGRAM_SETTINGS };
  }

  return {
    get settings() {
      return settings;
    },
    setWindowSize,
    setOverlap,
    setWindow,
    setColormap,
    setDBRange,
    setHeight,
    setTimeScale,
    setFreqScale,
    togglePCEN,
    toggleNormalize,
    toggleClamp,
    setAll,
    reset,
  };
}

export const spectrogramStore = createSpectrogramStore();
