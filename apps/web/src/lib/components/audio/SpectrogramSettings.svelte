<script lang="ts">
  import type { SpectrogramParams } from '$lib/types/data';
  import ColorMapPicker from './ColorMapPicker.svelte';

  export let params: SpectrogramParams = {};
  export let onChange: (params: SpectrogramParams) => void;
  export let samplerate: number = 48000;

  let nFft = params.n_fft ?? 2048;
  let hopLength = params.hop_length ?? 512;
  let freqMin = params.freq_min ?? 0;
  let freqMax = params.freq_max ?? Math.floor(samplerate / 2);
  let colormap = params.colormap ?? 'viridis';
  let pcen = params.pcen ?? false;
  let channel = params.channel ?? 0;

  const fftSizes = [512, 1024, 2048, 4096, 8192];

  function updateParams() {
    onChange({
      n_fft: nFft,
      hop_length: hopLength,
      freq_min: freqMin,
      freq_max: freqMax,
      colormap,
      pcen,
      channel,
    });
  }

  function handleColormapChange(newColormap: string) {
    colormap = newColormap;
    updateParams();
  }

  // Update local state when params change externally
  $: {
    if (params.n_fft !== undefined) nFft = params.n_fft;
    if (params.hop_length !== undefined) hopLength = params.hop_length;
    if (params.freq_min !== undefined) freqMin = params.freq_min;
    if (params.freq_max !== undefined) freqMax = params.freq_max;
    if (params.colormap !== undefined) colormap = params.colormap;
    if (params.pcen !== undefined) pcen = params.pcen;
    if (params.channel !== undefined) channel = params.channel;
  }
</script>

<div class="spectrogram-settings">
  <h4 class="settings-title">Spectrogram Settings</h4>

  <div class="settings-grid">
    <div class="setting-group">
      <label for="fft-size" class="setting-label">FFT Size</label>
      <select id="fft-size" bind:value={nFft} onchange={updateParams} class="setting-select">
        {#each fftSizes as size}
          <option value={size}>{size}</option>
        {/each}
      </select>
    </div>

    <div class="setting-group">
      <label for="hop-length" class="setting-label">Hop Length</label>
      <input
        id="hop-length"
        type="number"
        min="64"
        max={nFft}
        step="64"
        bind:value={hopLength}
        onchange={updateParams}
        class="setting-input"
      />
    </div>

    <div class="setting-group">
      <label for="channel" class="setting-label">Channel</label>
      <input
        id="channel"
        type="number"
        min="0"
        bind:value={channel}
        onchange={updateParams}
        class="setting-input"
      />
    </div>

    <div class="setting-group">
      <label for="freq-min" class="setting-label">Min Freq (Hz)</label>
      <input
        id="freq-min"
        type="number"
        min="0"
        max={samplerate / 2}
        bind:value={freqMin}
        onchange={updateParams}
        class="setting-input"
      />
    </div>

    <div class="setting-group">
      <label for="freq-max" class="setting-label">Max Freq (Hz)</label>
      <input
        id="freq-max"
        type="number"
        min="0"
        max={samplerate / 2}
        bind:value={freqMax}
        onchange={updateParams}
        class="setting-input"
      />
    </div>

    <div class="setting-group checkbox-group">
      <label class="checkbox-label">
        <input type="checkbox" bind:checked={pcen} onchange={updateParams} class="setting-checkbox" />
        <span>PCEN Normalization</span>
      </label>
    </div>
  </div>

  <div class="colormap-section">
    <label class="setting-label">Colormap</label>
    <ColorMapPicker value={colormap} onChange={handleColormapChange} />
  </div>
</div>

<style>
  .spectrogram-settings {
    padding: 1rem;
    background: #f9fafb;
    border-radius: 0.5rem;
    border: 1px solid #e5e7eb;
  }

  .settings-title {
    margin: 0 0 1rem 0;
    font-size: 0.875rem;
    font-weight: 600;
    color: #374151;
  }

  .settings-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 1rem;
    margin-bottom: 1rem;
  }

  .setting-group {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .setting-label {
    font-size: 0.75rem;
    font-weight: 500;
    color: #6b7280;
  }

  .setting-select,
  .setting-input {
    padding: 0.5rem 0.625rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.813rem;
    background: white;
    transition: border-color 0.15s ease;
  }

  .setting-select:focus,
  .setting-input:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
  }

  .checkbox-group {
    justify-content: flex-end;
  }

  .checkbox-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.813rem;
    color: #374151;
    cursor: pointer;
  }

  .setting-checkbox {
    width: 1rem;
    height: 1rem;
    cursor: pointer;
    accent-color: #3b82f6;
  }

  .colormap-section {
    padding-top: 1rem;
    border-top: 1px solid #e5e7eb;
  }

  .colormap-section .setting-label {
    display: block;
    margin-bottom: 0.5rem;
  }
</style>
