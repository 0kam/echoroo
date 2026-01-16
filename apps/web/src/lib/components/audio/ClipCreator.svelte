<script lang="ts">
  import { createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { createClip } from '$lib/api/clips';
  import type { ClipDetail } from '$lib/types/data';

  export let projectId: string;
  export let recordingId: string;
  export let duration: number;
  export let currentTime: number = 0;
  export let onCreated: ((clip: ClipDetail) => void) | undefined = undefined;

  let startTime = 0;
  let endTime = Math.min(10, duration);
  let note = '';

  const queryClient = useQueryClient();
  const createMut = createMutation({
    mutationFn: () =>
      createClip(projectId, recordingId, {
        start_time: startTime,
        end_time: endTime,
        note: note || undefined,
      }),
    onSuccess: (clip) => {
      queryClient.invalidateQueries({ queryKey: ['clips', projectId, recordingId] });
      onCreated?.(clip);
      resetSelection();
    },
  });

  function setStartFromCurrent() {
    startTime = parseFloat(currentTime.toFixed(2));
  }

  function setEndFromCurrent() {
    endTime = parseFloat(currentTime.toFixed(2));
  }

  function resetSelection() {
    startTime = 0;
    endTime = Math.min(10, duration);
    note = '';
  }

  export function setRange(start: number, end: number) {
    startTime = parseFloat(start.toFixed(2));
    endTime = parseFloat(end.toFixed(2));
  }

  $: clipDuration = endTime - startTime;
  $: isValid = endTime > startTime && startTime >= 0 && endTime <= duration;

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(2);
    return `${mins}:${secs.padStart(5, '0')}`;
  }

  function handleSubmit(event: Event) {
    event.preventDefault();
    if (isValid) {
      $createMut.mutate();
    }
  }
</script>

<div class="clip-creator">
  <h3 class="title">Create Clip</h3>

  <form on:submit={handleSubmit} class="form">
    <div class="time-inputs">
      <div class="time-field">
        <label for="start-time" class="label">Start Time (s)</label>
        <div class="time-input-group">
          <input
            id="start-time"
            type="number"
            step="0.01"
            min="0"
            max={duration}
            bind:value={startTime}
            class="input"
          />
          <button
            type="button"
            on:click={setStartFromCurrent}
            class="btn-from-current"
            aria-label="Set start time from current position"
          >
            <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <polyline points="9 11 12 14 22 4" stroke-width="2" />
              <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" stroke-width="2" />
            </svg>
          </button>
        </div>
        <span class="time-display">{formatTime(startTime)}</span>
      </div>

      <div class="time-field">
        <label for="end-time" class="label">End Time (s)</label>
        <div class="time-input-group">
          <input
            id="end-time"
            type="number"
            step="0.01"
            min="0"
            max={duration}
            bind:value={endTime}
            class="input"
          />
          <button
            type="button"
            on:click={setEndFromCurrent}
            class="btn-from-current"
            aria-label="Set end time from current position"
          >
            <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <polyline points="9 11 12 14 22 4" stroke-width="2" />
              <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" stroke-width="2" />
            </svg>
          </button>
        </div>
        <span class="time-display">{formatTime(endTime)}</span>
      </div>
    </div>

    <div class="note-field">
      <label for="clip-note" class="label">Note (optional)</label>
      <input
        id="clip-note"
        type="text"
        bind:value={note}
        placeholder="Add a note..."
        class="input"
      />
    </div>

    <div class="footer">
      <div class="duration-info">
        <span class="duration-label">Duration:</span>
        <span class="duration-value" class:invalid={!isValid}>
          {isValid ? clipDuration.toFixed(2) : '--'}s
        </span>
        {#if !isValid}
          <span class="error-text">Invalid time range</span>
        {/if}
      </div>

      <div class="actions">
        <button type="button" on:click={resetSelection} class="btn-reset">Reset</button>
        <button type="submit" disabled={$createMut.isPending || !isValid} class="btn-create">
          {$createMut.isPending ? 'Creating...' : 'Create Clip'}
        </button>
      </div>
    </div>

    {#if $createMut.error}
      <div class="error-message">
        <svg class="error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <circle cx="12" cy="12" r="10" stroke-width="2" />
          <line x1="12" y1="8" x2="12" y2="12" stroke-width="2" />
          <line x1="12" y1="16" x2="12.01" y2="16" stroke-width="2" />
        </svg>
        {$createMut.error.message}
      </div>
    {/if}
  </form>
</div>

<style>
  .clip-creator {
    padding: 1.5rem;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
  }

  .title {
    margin: 0 0 1.25rem 0;
    font-size: 1.125rem;
    font-weight: 600;
    color: #111827;
  }

  .form {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .time-inputs {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
  }

  .time-field {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .label {
    font-size: 0.875rem;
    font-weight: 500;
    color: #374151;
  }

  .time-input-group {
    display: flex;
    gap: 0.5rem;
  }

  .input {
    flex: 1;
    padding: 0.625rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    background: white;
    transition: all 0.15s ease;
  }

  .input:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  .btn-from-current {
    padding: 0.625rem;
    background: #e5e7eb;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .btn-from-current:hover {
    background: #dbeafe;
    border-color: #3b82f6;
  }

  .btn-from-current .icon {
    width: 18px;
    height: 18px;
    color: #374151;
  }

  .btn-from-current:hover .icon {
    color: #3b82f6;
  }

  .time-display {
    font-size: 0.75rem;
    color: #6b7280;
    font-family: monospace;
  }

  .note-field {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .duration-info {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
  }

  .duration-label {
    color: #6b7280;
    font-weight: 500;
  }

  .duration-value {
    color: #059669;
    font-weight: 600;
    font-family: monospace;
  }

  .duration-value.invalid {
    color: #dc2626;
  }

  .error-text {
    color: #dc2626;
    font-size: 0.75rem;
  }

  .actions {
    display: flex;
    gap: 0.75rem;
  }

  .btn-reset {
    padding: 0.625rem 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .btn-reset:hover {
    background: #f9fafb;
    border-color: #9ca3af;
  }

  .btn-create {
    padding: 0.625rem 1.25rem;
    font-size: 0.875rem;
    font-weight: 500;
    background: #3b82f6;
    color: white;
    border: 1px solid #3b82f6;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .btn-create:hover:not(:disabled) {
    background: #2563eb;
    border-color: #2563eb;
  }

  .btn-create:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .error-message {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem;
    background: #fee2e2;
    color: #991b1b;
    border-radius: 0.375rem;
    font-size: 0.875rem;
  }

  .error-icon {
    width: 18px;
    height: 18px;
    flex-shrink: 0;
  }
</style>
