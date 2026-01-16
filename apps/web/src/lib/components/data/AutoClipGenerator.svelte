<script lang="ts">
  import { createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { generateClips } from '$lib/api/clips';

  export let projectId: string;
  export let recordingId: string;
  export let duration: number;

  let clipLength = 3.0;
  let overlap = 0.0;
  let startTime = 0;
  let endTime: number | null = null;
  let showAdvanced = false;

  $: effectiveEndTime = endTime ?? duration;
  $: effectiveRange = Math.max(0, effectiveEndTime - startTime);
  $: stepSize = Math.max(0.01, clipLength - overlap);
  $: estimatedClips = stepSize > 0 ? Math.floor(effectiveRange / stepSize) : 0;

  const queryClient = useQueryClient();
  const generateMut = createMutation({
    mutationFn: () =>
      generateClips(projectId, recordingId, {
        clip_length: clipLength,
        overlap,
        start_time: startTime,
        end_time: endTime ?? undefined,
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['clips', projectId, recordingId] });
      queryClient.invalidateQueries({ queryKey: ['recording', projectId, recordingId] });
      // Reset advanced options
      showAdvanced = false;
      startTime = 0;
      endTime = null;
    },
  });

  $: isValid = clipLength > 0 && overlap >= 0 && overlap < clipLength && startTime >= 0 && effectiveEndTime <= duration;

  function handleSubmit(event: Event) {
    event.preventDefault();
    if (isValid) {
      $generateMut.mutate();
    }
  }
</script>

<div class="auto-clip-generator">
  <div class="header">
    <h3 class="title">Auto-Generate Clips</h3>
    <svg class="icon-wand" viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <path d="M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8L19 13M17.8 6.2L19 5M3 21l9-9M12.2 6.2L11 5" stroke-width="2" stroke-linecap="round" />
    </svg>
  </div>

  <form on:submit={handleSubmit} class="form">
    <div class="main-inputs">
      <div class="field">
        <label for="clip-length" class="label">Clip Length (seconds)</label>
        <input
          id="clip-length"
          type="number"
          step="0.5"
          min="0.1"
          bind:value={clipLength}
          class="input"
        />
      </div>

      <div class="field">
        <label for="overlap" class="label">Overlap (seconds)</label>
        <input
          id="overlap"
          type="number"
          step="0.1"
          min="0"
          max={clipLength - 0.1}
          bind:value={overlap}
          class="input"
        />
      </div>
    </div>

    <button type="button" on:click={() => (showAdvanced = !showAdvanced)} class="toggle-advanced">
      <svg
        class="icon-chevron"
        class:rotated={showAdvanced}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
      >
        <polyline points="6 9 12 15 18 9" stroke-width="2" stroke-linecap="round" />
      </svg>
      {showAdvanced ? 'Hide' : 'Show'} advanced options
    </button>

    {#if showAdvanced}
      <div class="advanced-section">
        <div class="advanced-inputs">
          <div class="field">
            <label for="start-time-gen" class="label">Start Time (seconds)</label>
            <input
              id="start-time-gen"
              type="number"
              step="0.1"
              min="0"
              max={duration}
              bind:value={startTime}
              class="input"
            />
          </div>

          <div class="field">
            <label for="end-time-gen" class="label">End Time (leave blank for end)</label>
            <input
              id="end-time-gen"
              type="number"
              step="0.1"
              min="0"
              max={duration}
              bind:value={endTime}
              class="input"
              placeholder={duration.toFixed(2)}
            />
          </div>
        </div>
      </div>
    {/if}

    <div class="footer">
      <div class="estimate">
        <svg class="icon-info" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <circle cx="12" cy="12" r="10" stroke-width="2" />
          <line x1="12" y1="16" x2="12" y2="12" stroke-width="2" stroke-linecap="round" />
          <line x1="12" y1="8" x2="12.01" y2="8" stroke-width="2" stroke-linecap="round" />
        </svg>
        <span class="estimate-text">
          Estimated clips: <strong>{estimatedClips > 0 ? estimatedClips : 0}</strong>
        </span>
      </div>

      <button type="submit" disabled={$generateMut.isPending || !isValid} class="btn-generate">
        {#if $generateMut.isPending}
          <svg class="spinner" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" opacity="0.25" />
            <path
              d="M12 2a10 10 0 0 1 10 10"
              stroke="currentColor"
              stroke-width="4"
              fill="none"
              stroke-linecap="round"
            />
          </svg>
          Generating...
        {:else}
          <svg class="icon-generate" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path d="M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8L19 13M17.8 6.2L19 5M3 21l9-9M12.2 6.2L11 5" stroke-width="2" stroke-linecap="round" />
          </svg>
          Generate Clips
        {/if}
      </button>
    </div>

    {#if $generateMut.isSuccess && $generateMut.data}
      <div class="success-message">
        <svg class="success-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" stroke-width="2" stroke-linecap="round" />
          <polyline points="22 4 12 14.01 9 11.01" stroke-width="2" stroke-linecap="round" />
        </svg>
        Successfully created {$generateMut.data.clips_created} clip{$generateMut.data.clips_created !== 1 ? 's' : ''}
      </div>
    {/if}

    {#if $generateMut.error}
      <div class="error-message">
        <svg class="error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <circle cx="12" cy="12" r="10" stroke-width="2" />
          <line x1="12" y1="8" x2="12" y2="12" stroke-width="2" />
          <line x1="12" y1="16" x2="12.01" y2="16" stroke-width="2" />
        </svg>
        {$generateMut.error.message}
      </div>
    {/if}
  </form>
</div>

<style>
  .auto-clip-generator {
    padding: 1.5rem;
    background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
    border: 1px solid #bfdbfe;
    border-radius: 0.5rem;
  }

  .header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1.25rem;
  }

  .title {
    margin: 0;
    font-size: 1.125rem;
    font-weight: 600;
    color: #1e3a8a;
  }

  .icon-wand {
    width: 24px;
    height: 24px;
    color: #3b82f6;
  }

  .form {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .main-inputs {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .label {
    font-size: 0.875rem;
    font-weight: 500;
    color: #1e3a8a;
  }

  .input {
    padding: 0.625rem 0.75rem;
    border: 1px solid #bfdbfe;
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

  .toggle-advanced {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0;
    background: none;
    border: none;
    color: #3b82f6;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    transition: color 0.15s ease;
  }

  .toggle-advanced:hover {
    color: #2563eb;
  }

  .icon-chevron {
    width: 16px;
    height: 16px;
    transition: transform 0.2s ease;
  }

  .icon-chevron.rotated {
    transform: rotate(180deg);
  }

  .advanced-section {
    padding-top: 1rem;
    border-top: 1px solid #bfdbfe;
  }

  .advanced-inputs {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
  }

  .footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .estimate {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    color: #1e3a8a;
  }

  .icon-info {
    width: 18px;
    height: 18px;
    color: #3b82f6;
  }

  .estimate-text {
    font-weight: 500;
  }

  .estimate-text strong {
    font-weight: 700;
    color: #1e40af;
  }

  .btn-generate {
    display: flex;
    align-items: center;
    gap: 0.5rem;
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

  .btn-generate:hover:not(:disabled) {
    background: #2563eb;
    border-color: #2563eb;
    box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.3);
  }

  .btn-generate:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .icon-generate {
    width: 18px;
    height: 18px;
  }

  .spinner {
    width: 18px;
    height: 18px;
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .success-message {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem;
    background: #d1fae5;
    color: #065f46;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    font-weight: 500;
  }

  .success-icon {
    width: 18px;
    height: 18px;
    flex-shrink: 0;
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
