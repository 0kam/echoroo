<script lang="ts">
  export let highpass: number | null = null;
  export let lowpass: number | null = null;
  export let samplerate: number = 48000;
  export let onChange: (highpass: number | null, lowpass: number | null) => void;

  let enableHighpass = highpass !== null;
  let enableLowpass = lowpass !== null;
  let highpassValue = highpass ?? 100;
  let lowpassValue = lowpass ?? Math.floor(samplerate / 2);

  function update() {
    onChange(enableHighpass ? highpassValue : null, enableLowpass ? lowpassValue : null);
  }

  function toggleHighpass() {
    enableHighpass = !enableHighpass;
    update();
  }

  function toggleLowpass() {
    enableLowpass = !enableLowpass;
    update();
  }

  // Update local state when props change
  $: {
    enableHighpass = highpass !== null;
    enableLowpass = lowpass !== null;
    if (highpass !== null) highpassValue = highpass;
    if (lowpass !== null) lowpassValue = lowpass;
  }
</script>

<div class="filter-settings">
  <h4 class="settings-title">Audio Filters</h4>

  <div class="filter-options">
    <div class="filter-row">
      <label class="filter-toggle">
        <input type="checkbox" checked={enableHighpass} onchange={toggleHighpass} class="filter-checkbox" />
        <span class="filter-name">Highpass Filter</span>
      </label>
      {#if enableHighpass}
        <div class="filter-value">
          <input
            type="number"
            min="0"
            max={samplerate / 2}
            bind:value={highpassValue}
            onchange={update}
            class="filter-input"
          />
          <span class="unit">Hz</span>
        </div>
      {/if}
    </div>

    <div class="filter-row">
      <label class="filter-toggle">
        <input type="checkbox" checked={enableLowpass} onchange={toggleLowpass} class="filter-checkbox" />
        <span class="filter-name">Lowpass Filter</span>
      </label>
      {#if enableLowpass}
        <div class="filter-value">
          <input
            type="number"
            min="0"
            max={samplerate / 2}
            bind:value={lowpassValue}
            onchange={update}
            class="filter-input"
          />
          <span class="unit">Hz</span>
        </div>
      {/if}
    </div>
  </div>

  {#if enableHighpass && enableLowpass && highpassValue >= lowpassValue}
    <div class="filter-warning">
      Warning: Highpass frequency should be lower than lowpass frequency
    </div>
  {/if}
</div>

<style>
  .filter-settings {
    padding: 1rem;
    background: #f9fafb;
    border-radius: 0.5rem;
    border: 1px solid #e5e7eb;
  }

  .settings-title {
    margin: 0 0 0.75rem 0;
    font-size: 0.875rem;
    font-weight: 600;
    color: #374151;
  }

  .filter-options {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .filter-row {
    display: flex;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .filter-toggle {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
    min-width: 140px;
  }

  .filter-checkbox {
    width: 1rem;
    height: 1rem;
    cursor: pointer;
    accent-color: #3b82f6;
  }

  .filter-name {
    font-size: 0.875rem;
    color: #374151;
  }

  .filter-value {
    display: flex;
    align-items: center;
    gap: 0.375rem;
  }

  .filter-input {
    width: 100px;
    padding: 0.375rem 0.5rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.813rem;
    background: white;
  }

  .filter-input:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
  }

  .unit {
    font-size: 0.75rem;
    color: #6b7280;
  }

  .filter-warning {
    margin-top: 0.75rem;
    padding: 0.5rem 0.75rem;
    background: #fef3c7;
    border: 1px solid #fcd34d;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    color: #92400e;
  }
</style>
