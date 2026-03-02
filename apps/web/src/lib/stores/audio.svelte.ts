/**
 * Svelte 5 rune-based store for audio playback settings.
 * These settings are shared across the application.
 */

import {
  DEFAULT_AUDIO_SETTINGS,
  type AudioSettings,
  MIN_SAMPLERATE,
  MAX_SAMPLERATE,
} from '$lib/types/audio';
import type { RecordingDetail } from '$lib/types/data';

function createAudioStore() {
  let settings = $state<AudioSettings>({ ...DEFAULT_AUDIO_SETTINGS });

  function setSpeed(speed: number) {
    if (speed <= 0) throw new Error('Speed must be greater than 0');
    settings.speed = speed;
  }

  function setSamplerate(samplerate: number) {
    if (samplerate < MIN_SAMPLERATE || samplerate > MAX_SAMPLERATE)
      throw new Error(`Sample rate must be between ${MIN_SAMPLERATE} and ${MAX_SAMPLERATE}`);
    settings.samplerate = samplerate;
  }

  function toggleResample() {
    settings.resample = !settings.resample;
  }

  function setChannel(channel: number) {
    if (channel < 0) throw new Error('Channel must be >= 0');
    settings.channel = channel;
  }

  function setFilter(opts: { lowFreq?: number | null; highFreq?: number | null; order?: number }) {
    const { lowFreq, highFreq, order } = opts;

    if (lowFreq !== undefined) {
      if (lowFreq !== null && lowFreq < 0) throw new Error('Low frequency must be >= 0');
      settings.low_freq = lowFreq ?? null;
    }

    if (highFreq !== undefined) {
      if (highFreq !== null && highFreq < 0) throw new Error('High frequency must be >= 0');
      if (
        highFreq !== null &&
        settings.low_freq !== null &&
        highFreq < settings.low_freq
      ) {
        throw new Error('High frequency must be >= low frequency');
      }
      settings.high_freq = highFreq ?? null;
    }

    if (order !== undefined) {
      if (order <= 0) throw new Error('Filter order must be > 0');
      settings.filter_order = order;
    }
  }

  /**
   * Adjust settings to be compatible with a given recording.
   * Clamps frequencies to Nyquist, etc.
   */
  function adjustToRecording(recording: RecordingDetail) {
    if (settings.samplerate === null) {
      settings.samplerate = recording.samplerate;
    }

    const effectiveSamplerate = settings.resample
      ? (settings.samplerate ?? recording.samplerate)
      : recording.samplerate;

    const nyquist = effectiveSamplerate / 2;

    if (settings.low_freq !== null) {
      settings.low_freq = Math.min(settings.low_freq, nyquist);
    }

    if (settings.high_freq !== null) {
      settings.high_freq = Math.min(settings.high_freq, nyquist);
    }

    if (settings.low_freq !== null && settings.high_freq !== null) {
      if (settings.low_freq > settings.high_freq) {
        settings.high_freq = settings.low_freq;
      }
    }
  }

  function setAll(newSettings: AudioSettings) {
    settings = { ...newSettings };
  }

  function reset() {
    settings = { ...DEFAULT_AUDIO_SETTINGS };
  }

  return {
    get settings() {
      return settings;
    },
    setSpeed,
    setSamplerate,
    toggleResample,
    setChannel,
    setFilter,
    adjustToRecording,
    setAll,
    reset,
  };
}

export const audioStore = createAudioStore();
