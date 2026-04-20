<script lang="ts">
  import { untrack } from 'svelte';
  import type { AudioSettings } from '$lib/types/audio';
  import { MIN_SAMPLERATE, MAX_SAMPLERATE } from '$lib/types/audio';

  interface Props {
    settings: AudioSettings;
    samplerate: number;
    onChange: (settings: AudioSettings) => void;
  }

  let { settings, samplerate, onChange }: Props = $props();

  // Local editable copies of the filter values; synced from `settings`
  // via the $effect below when the parent updates. Initial values are
  // captured via untrack() so they are not flagged as non-reactive refs.
  let localLowFreq = $state<number>(untrack(() => settings.low_freq ?? 0));
  let localHighFreq = $state<number>(untrack(() => settings.high_freq ?? samplerate / 2));
  let localSamplerate = $state<number>(untrack(() => settings.samplerate ?? samplerate));
  let localFilterOrder = $state<number>(untrack(() => settings.filter_order));

  const nyquist = $derived(
    settings.resample ? (settings.samplerate ?? samplerate) / 2 : samplerate / 2
  );

  function toggleResample() {
    onChange({ ...settings, resample: !settings.resample });
  }

  function handleSamplerateChange(e: Event) {
    const v = parseInt((e.target as HTMLInputElement).value, 10);
    localSamplerate = v;
    if (v >= MIN_SAMPLERATE && v <= MAX_SAMPLERATE) {
      onChange({ ...settings, samplerate: v });
    }
  }

  function handleLowFreqToggle(e: Event) {
    const checked = (e.target as HTMLInputElement).checked;
    onChange({ ...settings, low_freq: checked ? localLowFreq : null });
  }

  function handleHighFreqToggle(e: Event) {
    const checked = (e.target as HTMLInputElement).checked;
    onChange({ ...settings, high_freq: checked ? localHighFreq : null });
  }

  function handleLowFreqChange(e: Event) {
    const v = parseFloat((e.target as HTMLInputElement).value);
    localLowFreq = v;
    if (settings.low_freq !== null) {
      onChange({ ...settings, low_freq: v });
    }
  }

  function handleHighFreqChange(e: Event) {
    const v = parseFloat((e.target as HTMLInputElement).value);
    localHighFreq = v;
    if (settings.high_freq !== null) {
      onChange({ ...settings, high_freq: v });
    }
  }

  function handleFilterOrderChange(e: Event) {
    const v = parseInt((e.target as HTMLInputElement).value, 10);
    localFilterOrder = v;
    onChange({ ...settings, filter_order: v });
  }

  // Validate frequency ordering
  const hasFreqError = $derived(
    settings.low_freq !== null &&
    settings.high_freq !== null &&
    settings.low_freq >= settings.high_freq
  );

  // Sync local state with parent
  $effect(() => {
    if (settings.low_freq !== null) localLowFreq = settings.low_freq;
    if (settings.high_freq !== null) localHighFreq = settings.high_freq;
    if (settings.samplerate !== null) localSamplerate = settings.samplerate;
    localFilterOrder = settings.filter_order;
  });
</script>

<div class="filter-panel">
  <h5 class="section-title">Audio Filters</h5>

  <!-- Resample toggle -->
  <div class="filter-group">
    <div class="filter-row">
      <label class="filter-toggle-label">
        <input
          type="checkbox"
          checked={settings.resample}
          onchange={toggleResample}
          class="checkbox"
        />
        <span>Resample audio</span>
      </label>
    </div>

    {#if settings.resample}
      <div class="filter-row indent">
        <label class="filter-label" for="target-samplerate">Target sample rate (Hz)</label>
        <input
          id="target-samplerate"
          type="number"
          min={MIN_SAMPLERATE}
          max={MAX_SAMPLERATE}
          step="1000"
          value={localSamplerate}
          oninput={handleSamplerateChange}
          class="filter-input"
        />
      </div>
    {/if}
  </div>

  <!-- Frequency range -->
  <div class="filter-group">
    <h6 class="filter-group-title">Frequency Range</h6>

    <div class="filter-row">
      <label class="filter-toggle-label">
        <input
          type="checkbox"
          checked={settings.low_freq !== null}
          onchange={handleLowFreqToggle}
          class="checkbox"
        />
        <span>Highpass (low cut) Hz</span>
      </label>
      {#if settings.low_freq !== null}
        <input
          type="number"
          min="0"
          max={nyquist}
          step="100"
          value={localLowFreq}
          oninput={handleLowFreqChange}
          class="filter-input"
        />
      {/if}
    </div>

    <div class="filter-row">
      <label class="filter-toggle-label">
        <input
          type="checkbox"
          checked={settings.high_freq !== null}
          onchange={handleHighFreqToggle}
          class="checkbox"
        />
        <span>Lowpass (high cut) Hz</span>
      </label>
      {#if settings.high_freq !== null}
        <input
          type="number"
          min="0"
          max={nyquist}
          step="100"
          value={localHighFreq}
          oninput={handleHighFreqChange}
          class="filter-input"
        />
      {/if}
    </div>

    {#if hasFreqError}
      <p class="filter-warning">Highpass frequency must be less than lowpass frequency.</p>
    {/if}
  </div>

  <!-- Filter order -->
  {#if settings.low_freq !== null || settings.high_freq !== null}
    <div class="filter-group">
      <div class="filter-row">
        <label class="filter-label" for="filter-order">Filter order</label>
        <input
          id="filter-order"
          type="number"
          min="1"
          max="10"
          value={localFilterOrder}
          oninput={handleFilterOrderChange}
          class="filter-input w-16"
        />
      </div>
    </div>
  {/if}
</div>

<style>
  .filter-panel {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 1rem;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
  }

  :global(.dark) .filter-panel {
    background: #27272a;
    border-color: #3f3f46;
  }

  .section-title {
    margin: 0;
    font-size: 0.875rem;
    font-weight: 600;
    color: #374151;
  }

  :global(.dark) .section-title {
    color: #d4d4d8;
  }

  .filter-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .filter-group-title {
    margin: 0;
    font-size: 0.75rem;
    font-weight: 500;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  :global(.dark) .filter-group-title {
    color: #a1a1aa;
  }

  .filter-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .indent {
    padding-left: 1.5rem;
  }

  .filter-toggle-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    color: #374151;
    cursor: pointer;
  }

  :global(.dark) .filter-toggle-label {
    color: #d4d4d8;
  }

  .filter-label {
    font-size: 0.875rem;
    color: #374151;
    min-width: 12rem;
  }

  :global(.dark) .filter-label {
    color: #d4d4d8;
  }

  .checkbox {
    width: 1rem;
    height: 1rem;
    cursor: pointer;
    accent-color: #10b981;
  }

  .filter-input {
    padding: 0.375rem 0.5rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    background: white;
    color: #374151;
    width: 9rem;
  }

  :global(.dark) .filter-input {
    background: #3f3f46;
    border-color: #52525b;
    color: #d4d4d8;
  }

  .filter-input:focus {
    outline: none;
    border-color: #10b981;
    box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
  }

  .filter-warning {
    margin: 0;
    padding: 0.5rem 0.75rem;
    background: #fef3c7;
    border: 1px solid #fcd34d;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    color: #92400e;
  }
</style>
