<script lang="ts">
  import { getSpeedOptions, type SpeedOption } from '$lib/types/audio';

  interface Props {
    speed: number;
    samplerate: number;
    onChange: (speed: number) => void;
  }

  let { speed, samplerate, onChange }: Props = $props();

  let availableOptions = $derived(getSpeedOptions(samplerate));

  function handleSelect(option: SpeedOption) {
    onChange(option.value);
  }
</script>

<div class="speed-control">
  <span class="speed-label">Speed</span>
  <div class="speed-buttons">
    {#each availableOptions as option}
      <button
        type="button"
        class="speed-btn {speed === option.value ? 'speed-btn-active' : 'speed-btn-inactive'}"
        onclick={() => handleSelect(option)}
      >
        {option.label}
      </button>
    {/each}
  </div>
</div>

<style>
  .speed-control {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .speed-label {
    font-size: 0.875rem;
    font-weight: 500;
    color: #6b7280;
    flex-shrink: 0;
  }

  :global(.dark) .speed-label {
    color: #a1a1aa;
  }

  .speed-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
  }

  .speed-btn {
    padding: 0.25rem 0.625rem;
    border-radius: 0.375rem;
    font-size: 0.8125rem;
    font-weight: 500;
    font-family: monospace;
    cursor: pointer;
    border: 1px solid;
    transition: all 0.15s ease;
  }

  .speed-btn-inactive {
    background: white;
    border-color: #d1d5db;
    color: #374151;
  }

  :global(.dark) .speed-btn-inactive {
    background: #3f3f46;
    border-color: #52525b;
    color: #d4d4d8;
  }

  .speed-btn-inactive:hover {
    border-color: #10b981;
    color: #10b981;
  }

  .speed-btn-active {
    background: #10b981;
    border-color: #059669;
    color: white;
  }

  .speed-btn-active:hover {
    background: #059669;
  }

  .speed-btn:focus-visible {
    outline: 2px solid #10b981;
    outline-offset: 1px;
  }
</style>
