<script lang="ts">
  /**
   * ExportDialog component for exporting datasets in CamtrapDP format.
   */

  export let projectId: string;
  export let datasetId: string;
  export let datasetName: string;
  export let isOpen: boolean = false;
  export let onClose: () => void;

  let includeAudio = false;
  let isExporting = false;

  function getExportUrl(): string {
    const params = new URLSearchParams();
    if (includeAudio) params.append('include_audio', 'true');
    const queryString = params.toString();
    return `/api/v1/projects/${projectId}/datasets/${datasetId}/export${queryString ? `?${queryString}` : ''}`;
  }

  async function startExport() {
    isExporting = true;

    // Trigger download via link
    const link = document.createElement('a');
    link.href = getExportUrl();
    link.download = `${datasetName.replace(/\s+/g, '_')}_export.zip`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    // Close after a delay
    setTimeout(() => {
      isExporting = false;
      onClose();
    }, 1000);
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && isOpen) {
      onClose();
    }
  }
</script>

<svelte:window on:keydown={handleKeydown} />

{#if isOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-overlay" on:click={onClose}>
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="modal" on:click|stopPropagation>
      <div class="modal-header">
        <h3>Export Dataset</h3>
        <button type="button" class="close-btn" on:click={onClose} aria-label="Close">
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <line x1="18" y1="6" x2="6" y2="18" stroke-width="2" />
            <line x1="6" y1="6" x2="18" y2="18" stroke-width="2" />
          </svg>
        </button>
      </div>

      <div class="modal-body">
        <p class="description">
          Export "<strong>{datasetName}</strong>" in CamtrapDP format. This includes metadata files
          (deployments.csv, media.csv) and a datapackage.json file.
        </p>

        <div class="export-options">
          <label class="option-item">
            <input type="checkbox" bind:checked={includeAudio} />
            <div class="option-content">
              <span class="option-label">Include audio files</span>
              <span class="option-hint">Warning: This may result in a very large download</span>
            </div>
          </label>
        </div>

        <div class="export-info">
          <h4>Export contents:</h4>
          <ul>
            <li><code>datapackage.json</code> - Dataset metadata</li>
            <li><code>deployments.csv</code> - Deployment information</li>
            <li><code>media.csv</code> - Recording metadata</li>
            {#if includeAudio}
              <li><code>data/</code> - Audio files</li>
            {/if}
          </ul>
        </div>
      </div>

      <div class="modal-footer">
        <button type="button" class="btn-secondary" on:click={onClose} disabled={isExporting}>
          Cancel
        </button>
        <button
          type="button"
          class="btn-primary"
          on:click={startExport}
          disabled={isExporting}
        >
          {#if isExporting}
            <svg class="spinner" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" opacity="0.25" />
              <path
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            Exporting...
          {:else}
            <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke-width="2" />
              <polyline points="7 10 12 15 17 10" stroke-width="2" />
              <line x1="12" y1="15" x2="12" y2="3" stroke-width="2" />
            </svg>
            Export
          {/if}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: 1rem;
  }

  .modal {
    background: white;
    border-radius: 0.5rem;
    max-width: 500px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 1.5rem;
    border-bottom: 1px solid #e5e7eb;
  }

  .modal-header h3 {
    margin: 0;
    font-size: 1.125rem;
    font-weight: 600;
    color: #111827;
  }

  .close-btn {
    background: none;
    border: none;
    padding: 0.25rem;
    cursor: pointer;
    color: #9ca3af;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 0.25rem;
  }

  .close-btn:hover {
    color: #4b5563;
    background: #f3f4f6;
  }

  .close-btn .icon {
    width: 20px;
    height: 20px;
  }

  .modal-body {
    padding: 1.5rem;
  }

  .description {
    margin: 0 0 1.5rem 0;
    color: #6b7280;
    font-size: 0.875rem;
    line-height: 1.5;
  }

  .description strong {
    color: #111827;
  }

  .export-options {
    margin-bottom: 1.5rem;
  }

  .option-item {
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    padding: 1rem;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .option-item:hover {
    background: #f9fafb;
    border-color: #d1d5db;
  }

  .option-item input[type='checkbox'] {
    margin-top: 0.125rem;
    width: 16px;
    height: 16px;
    cursor: pointer;
  }

  .option-content {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .option-label {
    font-size: 0.875rem;
    font-weight: 500;
    color: #111827;
  }

  .option-hint {
    font-size: 0.75rem;
    color: #f59e0b;
  }

  .export-info {
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    padding: 1rem;
  }

  .export-info h4 {
    margin: 0 0 0.75rem 0;
    font-size: 0.75rem;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .export-info ul {
    margin: 0;
    padding-left: 1.25rem;
    font-size: 0.875rem;
    color: #374151;
  }

  .export-info li {
    margin-bottom: 0.25rem;
  }

  .export-info code {
    background: #e5e7eb;
    padding: 0.125rem 0.375rem;
    border-radius: 0.25rem;
    font-family: monospace;
    font-size: 0.75rem;
  }

  .modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    padding: 1rem 1.5rem;
    border-top: 1px solid #e5e7eb;
    background: #f9fafb;
    border-radius: 0 0 0.5rem 0.5rem;
  }

  .btn-secondary,
  .btn-primary {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.625rem 1.25rem;
    font-size: 0.875rem;
    font-weight: 500;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .btn-secondary {
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .btn-secondary:hover:not(:disabled) {
    background: #f9fafb;
  }

  .btn-primary {
    background: #3b82f6;
    color: white;
    border: none;
  }

  .btn-primary:hover:not(:disabled) {
    background: #2563eb;
  }

  .btn-primary:disabled,
  .btn-secondary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-primary .icon,
  .btn-primary .spinner {
    width: 18px;
    height: 18px;
  }

  .spinner {
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }
</style>
