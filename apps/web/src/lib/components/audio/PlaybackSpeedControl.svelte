<script lang="ts">
  export let speed: number = 1.0;
  export let isUltrasonic: boolean = false;
  export let onChange: (speed: number) => void;

  const normalSpeeds = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0];
  const ultrasonicSpeeds = [0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0];

  $: availableSpeeds = isUltrasonic ? ultrasonicSpeeds : normalSpeeds;

  function handleChange(event: Event) {
    const target = event.target as HTMLSelectElement;
    onChange(parseFloat(target.value));
  }
</script>

<div class="speed-control">
  <label for="speed-select" class="label">Playback Speed:</label>
  <select id="speed-select" value={speed} on:change={handleChange} class="speed-select">
    {#each availableSpeeds as s}
      <option value={s}>{s}x</option>
    {/each}
  </select>
  {#if isUltrasonic}
    <span class="ultrasonic-badge">
      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M12 2v20M2 12h20" stroke-width="2" />
        <path d="M12 7c2.76 0 5 2.24 5 5s-2.24 5-5 5-5-2.24-5-5 2.24-5 5-5z" stroke-width="2" />
      </svg>
      Ultrasonic
    </span>
  {/if}
</div>

<style>
  .speed-control {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 0.375rem;
  }

  .label {
    font-size: 0.875rem;
    font-weight: 500;
    color: #374151;
    white-space: nowrap;
  }

  .speed-select {
    padding: 0.5rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    background: white;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .speed-select:hover {
    border-color: #3b82f6;
  }

  .speed-select:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  .ultrasonic-badge {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.25rem 0.5rem;
    background: #fef3c7;
    color: #92400e;
    border-radius: 0.25rem;
    font-size: 0.75rem;
    font-weight: 500;
    white-space: nowrap;
  }

  .icon {
    width: 14px;
    height: 14px;
    color: #f59e0b;
  }
</style>
