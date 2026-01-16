<script lang="ts">
  import type { Site, SiteCreate } from '$lib/types/data';
  import H3MapPicker from '$lib/components/map/H3MapPicker.svelte';

  export let site: Site | null = null;
  export let onSubmit: (data: SiteCreate) => Promise<void>;
  export let onCancel: () => void = () => {};

  let name = site?.name ?? '';
  let h3Index = site?.h3_index ?? '';
  let resolution = 9;
  let isSubmitting = false;
  let error = '';

  function handleMapSelect(index: string, center: [number, number]) {
    h3Index = index;
  }

  async function handleSubmit() {
    if (!name.trim()) {
      error = 'Name is required';
      return;
    }
    if (!h3Index) {
      error = 'Please select a location on the map';
      return;
    }

    error = '';
    isSubmitting = true;

    try {
      await onSubmit({ name: name.trim(), h3_index: h3Index });
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to save site';
    } finally {
      isSubmitting = false;
    }
  }
</script>

<form class="site-form" on:submit|preventDefault={handleSubmit}>
  <div class="form-group">
    <label for="name">Site Name *</label>
    <input
      type="text"
      id="name"
      bind:value={name}
      placeholder="Enter site name"
      maxlength="200"
      required
    />
  </div>

  <div class="form-group">
    <label>Location *</label>
    <p class="help-text">Click on the map to select an H3 hexagon for this site.</p>
    <H3MapPicker h3Index={h3Index} {resolution} onSelect={handleMapSelect} />
  </div>

  {#if h3Index}
    <div class="form-group">
      <label>Selected H3 Index</label>
      <input type="text" value={h3Index} readonly class="readonly" />
    </div>
  {/if}

  {#if error}
    <div class="error-message">{error}</div>
  {/if}

  <div class="form-actions">
    <button type="button" class="btn-secondary" on:click={onCancel} disabled={isSubmitting}>
      Cancel
    </button>
    <button type="submit" class="btn-primary" disabled={isSubmitting || !name || !h3Index}>
      {#if isSubmitting}
        Saving...
      {:else}
        {site ? 'Update Site' : 'Create Site'}
      {/if}
    </button>
  </div>
</form>

<style>
  .site-form {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .form-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .form-group label {
    font-weight: 500;
    font-size: 0.875rem;
    color: #374151;
  }

  .help-text {
    font-size: 0.75rem;
    color: #6b7280;
    margin: 0;
  }

  input[type='text'] {
    padding: 0.625rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    transition: border-color 0.15s ease;
  }

  input[type='text']:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  input.readonly {
    background: #f9fafb;
    color: #6b7280;
    font-family: monospace;
  }

  .error-message {
    padding: 0.75rem;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 0.375rem;
    color: #dc2626;
    font-size: 0.875rem;
  }

  .form-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    padding-top: 1rem;
    border-top: 1px solid #e5e7eb;
  }

  .btn-primary,
  .btn-secondary {
    padding: 0.625rem 1.25rem;
    font-size: 0.875rem;
    font-weight: 500;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .btn-primary {
    background: #3b82f6;
    color: white;
    border: none;
  }

  .btn-primary:hover:not(:disabled) {
    background: #2563eb;
  }

  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-secondary {
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .btn-secondary:hover:not(:disabled) {
    background: #f9fafb;
  }
</style>
