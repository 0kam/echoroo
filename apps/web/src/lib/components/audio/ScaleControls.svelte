<script lang="ts">
  import type { SpectrogramSettings } from '$lib/types/audio';
  import { SCALE_MIN, SCALE_MAX, SCALE_STEP } from '$lib/types/audio';

  interface Props {
    settings: SpectrogramSettings;
    onChange: (settings: SpectrogramSettings) => void;
  }

  let { settings, onChange }: Props = $props();

  function handleTimeScaleChange(e: Event) {
    const v = parseFloat((e.target as HTMLInputElement).value);
    onChange({ ...settings, time_scale: v });
  }

  function handleFreqScaleChange(e: Event) {
    const v = parseFloat((e.target as HTMLInputElement).value);
    onChange({ ...settings, freq_scale: v });
  }
</script>

<div class="scale-controls">
  <div class="scale-item">
    <label class="scale-label" for="time-scale">
      <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M5 12h14M12 5l7 7-7 7" />
      </svg>
      Time scale
    </label>
    <input
      id="time-scale"
      type="range"
      min={SCALE_MIN}
      max={SCALE_MAX}
      step={SCALE_STEP}
      value={settings.time_scale}
      oninput={handleTimeScaleChange}
      class="scale-slider"
    />
    <span class="scale-value">{settings.time_scale.toFixed(1)}x</span>
  </div>

  <div class="scale-item">
    <label class="scale-label" for="freq-scale">
      <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 5v14M5 12l7 7 7-7" />
      </svg>
      Freq scale
    </label>
    <input
      id="freq-scale"
      type="range"
      min={SCALE_MIN}
      max={SCALE_MAX}
      step={SCALE_STEP}
      value={settings.freq_scale}
      oninput={handleFreqScaleChange}
      class="scale-slider"
    />
    <span class="scale-value">{settings.freq_scale.toFixed(1)}x</span>
  </div>
</div>

<style>
  .scale-controls {
    display: flex;
    gap: 1.5rem;
    align-items: center;
    flex-wrap: wrap;
  }

  .scale-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .scale-label {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.75rem;
    color: #6b7280;
    white-space: nowrap;
    flex-shrink: 0;
  }

  :global(.dark) .scale-label {
    color: #a1a1aa;
  }

  .scale-slider {
    width: 6rem;
    height: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: #e5e7eb;
    border-radius: 2px;
    cursor: pointer;
    accent-color: #10b981;
  }

  :global(.dark) .scale-slider {
    background: #3f3f46;
  }

  .scale-value {
    font-size: 0.75rem;
    font-family: monospace;
    color: #6b7280;
    min-width: 2.5rem;
  }

  :global(.dark) .scale-value {
    color: #a1a1aa;
  }
</style>
