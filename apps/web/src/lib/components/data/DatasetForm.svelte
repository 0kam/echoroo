<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { fetchSites } from '$lib/api/sites';
  import DirectoryBrowser from './DirectoryBrowser.svelte';
  import DatetimePatternTester from './DatetimePatternTester.svelte';
  import VisibilitySelector from './VisibilitySelector.svelte';
  import type { DatasetCreate, DatasetDetail, DatasetUpdate, DatasetVisibility } from '$lib/types/data';

  export let projectId: string;
  export let dataset: DatasetDetail | null = null;
  export let onSubmit: (data: DatasetCreate | DatasetUpdate) => Promise<void>;
  export let onCancel: () => void = () => {};

  const isEdit = !!dataset;

  // Form fields
  let name = dataset?.name ?? '';
  let description = dataset?.description ?? '';
  let audioDir = dataset?.audio_dir ?? '';
  let visibility: DatasetVisibility = dataset?.visibility ?? 'private';
  let siteId = dataset?.site_id ?? '';
  let recorderId = dataset?.recorder_id ?? '';
  let licenseId = dataset?.license_id ?? '';
  let doi = dataset?.doi ?? '';
  let gain = dataset?.gain?.toString() ?? '';
  let note = dataset?.note ?? '';
  let datetimePattern = '';
  let datetimeFormat = '';

  let showDirectoryBrowser = false;
  let isSubmitting = false;
  let error = '';

  // Fetch sites for dropdown
  const sitesQuery = createQuery({
    queryKey: ['sites', projectId],
    queryFn: () => fetchSites(projectId, { page_size: 100 }),
  });

  function handleDirectorySelect(path: string) {
    audioDir = path;
    showDirectoryBrowser = false;
  }

  async function handleSubmit() {
    // Validation
    if (!name.trim()) {
      error = 'Name is required';
      return;
    }
    if (!audioDir.trim()) {
      error = 'Audio directory is required';
      return;
    }
    if (!siteId) {
      error = 'Site is required';
      return;
    }

    error = '';
    isSubmitting = true;

    try {
      if (isEdit) {
        const updateData: DatasetUpdate = {
          name: name.trim(),
          description: description.trim() || null,
          visibility,
          recorder_id: recorderId || null,
          license_id: licenseId || null,
          doi: doi.trim() || null,
          gain: gain ? parseFloat(gain) : null,
          note: note.trim() || null,
          datetime_pattern: datetimePattern.trim() || null,
          datetime_format: datetimeFormat.trim() || null,
        };
        await onSubmit(updateData);
      } else {
        const createData: DatasetCreate = {
          site_id: siteId,
          name: name.trim(),
          description: description.trim() || null,
          audio_dir: audioDir.trim(),
          visibility,
          recorder_id: recorderId || null,
          license_id: licenseId || null,
          doi: doi.trim() || null,
          gain: gain ? parseFloat(gain) : null,
          note: note.trim() || null,
          datetime_pattern: datetimePattern.trim() || null,
          datetime_format: datetimeFormat.trim() || null,
        };
        await onSubmit(createData);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to save dataset';
    } finally {
      isSubmitting = false;
    }
  }
</script>

<form class="dataset-form" on:submit|preventDefault={handleSubmit}>
  <div class="form-row">
    <div class="form-group full-width">
      <label for="name">Name *</label>
      <input
        id="name"
        type="text"
        bind:value={name}
        placeholder="Enter dataset name"
        maxlength="200"
        required
      />
    </div>
  </div>

  <div class="form-row">
    <div class="form-group full-width">
      <label for="description">Description</label>
      <textarea
        id="description"
        bind:value={description}
        placeholder="Describe this dataset"
        rows="3"
      ></textarea>
    </div>
  </div>

  <div class="form-row">
    <div class="form-group">
      <label for="site">Site *</label>
      {#if $sitesQuery.isLoading}
        <select id="site" disabled>
          <option>Loading sites...</option>
        </select>
      {:else if $sitesQuery.isError}
        <div class="field-error">Error loading sites</div>
      {:else if $sitesQuery.data}
        <select id="site" bind:value={siteId} required disabled={isEdit}>
          <option value="">Select a site</option>
          {#each $sitesQuery.data.items as site}
            <option value={site.id}>{site.name}</option>
          {/each}
        </select>
        {#if isEdit}
          <p class="help-text">Site cannot be changed after creation</p>
        {/if}
      {/if}
    </div>

    <div class="form-group">
      <VisibilitySelector
        value={visibility}
        onChange={(v) => (visibility = v)}
      />
    </div>
  </div>

  <div class="form-row">
    <div class="form-group full-width">
      <label for="audio-dir">Audio Directory *</label>
      <div class="directory-input-group">
        <input
          id="audio-dir"
          type="text"
          bind:value={audioDir}
          placeholder="/path/to/audio/files"
          required
          readonly={isEdit}
        />
        {#if !isEdit}
          <button type="button" class="browse-btn" on:click={() => (showDirectoryBrowser = !showDirectoryBrowser)}>
            Browse
          </button>
        {/if}
      </div>
      {#if isEdit}
        <p class="help-text">Directory cannot be changed after creation</p>
      {/if}
    </div>
  </div>

  {#if showDirectoryBrowser && !isEdit}
    <div class="form-row">
      <div class="form-group full-width">
        <DirectoryBrowser selectedPath={audioDir} onSelect={handleDirectorySelect} />
      </div>
    </div>
  {/if}

  <!-- Advanced options -->
  <details class="advanced-section">
    <summary>Advanced Options</summary>

    <div class="advanced-content">
      <div class="form-row">
        <div class="form-group">
          <label for="recorder">Recorder</label>
          <input
            id="recorder"
            type="text"
            bind:value={recorderId}
            placeholder="Recorder ID (optional)"
          />
          <p class="help-text">ID of the recording device used</p>
        </div>

        <div class="form-group">
          <label for="license">License</label>
          <input
            id="license"
            type="text"
            bind:value={licenseId}
            placeholder="License ID (optional)"
          />
          <p class="help-text">Data license identifier</p>
        </div>
      </div>

      <div class="form-row">
        <div class="form-group">
          <label for="doi">DOI</label>
          <input id="doi" type="text" bind:value={doi} placeholder="10.xxxx/xxxxx (optional)" />
        </div>

        <div class="form-group">
          <label for="gain">Gain (dB)</label>
          <input
            id="gain"
            type="number"
            step="0.1"
            bind:value={gain}
            placeholder="0.0"
          />
        </div>
      </div>

      <div class="form-row">
        <div class="form-group full-width">
          <label for="note">Note</label>
          <textarea id="note" bind:value={note} placeholder="Additional notes" rows="2"></textarea>
        </div>
      </div>

      <!-- Datetime extraction -->
      <div class="datetime-section">
        <h4>Datetime Extraction (Optional)</h4>
        <p class="section-help">
          Configure how to extract recording datetime from filenames. If not provided, file modification time will be used.
        </p>

        <div class="form-row">
          <div class="form-group">
            <label for="datetime-pattern">Regex Pattern</label>
            <input
              id="datetime-pattern"
              type="text"
              bind:value={datetimePattern}
              placeholder="e.g., (\d{8}_\d{6})"
              class="monospace"
            />
            <p class="help-text">Regular expression to extract datetime from filename</p>
          </div>

          <div class="form-group">
            <label for="datetime-format">Datetime Format</label>
            <input
              id="datetime-format"
              type="text"
              bind:value={datetimeFormat}
              placeholder="e.g., %Y%m%d_%H%M%S"
              class="monospace"
            />
            <p class="help-text">Python strptime format for parsing</p>
          </div>
        </div>

        {#if datetimePattern || datetimeFormat}
          <DatetimePatternTester pattern={datetimePattern} format={datetimeFormat} />
        {/if}
      </div>
    </div>
  </details>

  {#if error}
    <div class="error-message">{error}</div>
  {/if}

  <div class="form-actions">
    <button type="button" class="btn-secondary" on:click={onCancel} disabled={isSubmitting}>
      Cancel
    </button>
    <button type="submit" class="btn-primary" disabled={isSubmitting || !name || !audioDir || !siteId}>
      {#if isSubmitting}
        Saving...
      {:else}
        {isEdit ? 'Update Dataset' : 'Create Dataset'}
      {/if}
    </button>
  </div>
</form>

<style>
  .dataset-form {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .form-row {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 1rem;
  }

  .form-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .form-group.full-width {
    grid-column: 1 / -1;
  }

  .form-group label {
    font-weight: 500;
    font-size: 0.875rem;
    color: #374151;
  }

  input[type='text'],
  input[type='number'],
  select,
  textarea {
    padding: 0.625rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    transition: border-color 0.15s ease;
  }

  input[type='text']:focus,
  input[type='number']:focus,
  select:focus,
  textarea:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  input:read-only,
  select:disabled {
    background: #f9fafb;
    color: #6b7280;
    cursor: not-allowed;
  }

  textarea {
    resize: vertical;
    font-family: inherit;
  }

  .monospace {
    font-family: monospace;
  }

  .help-text {
    font-size: 0.75rem;
    color: #6b7280;
    margin: 0;
  }

  .field-error {
    padding: 0.5rem;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 0.375rem;
    color: #dc2626;
    font-size: 0.875rem;
  }

  .directory-input-group {
    display: flex;
    gap: 0.5rem;
  }

  .directory-input-group input {
    flex: 1;
  }

  .browse-btn {
    padding: 0.625rem 1rem;
    background: white;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .browse-btn:hover {
    background: #f9fafb;
    border-color: #3b82f6;
  }

  .advanced-section {
    border: 1px solid #e5e7eb;
    border-radius: 0.375rem;
    padding: 1rem;
    background: #f9fafb;
  }

  .advanced-section summary {
    cursor: pointer;
    font-weight: 500;
    color: #374151;
    user-select: none;
  }

  .advanced-section summary:hover {
    color: #3b82f6;
  }

  .advanced-content {
    margin-top: 1rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .datetime-section {
    margin-top: 1rem;
    padding-top: 1rem;
    border-top: 1px solid #e5e7eb;
  }

  .datetime-section h4 {
    margin: 0 0 0.5rem 0;
    font-size: 0.875rem;
    font-weight: 600;
    color: #374151;
  }

  .section-help {
    margin: 0 0 1rem 0;
    font-size: 0.75rem;
    color: #6b7280;
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
