<script lang="ts">
  /**
   * Export dialog for annotation project data (annotations, tasks, clip data).
   */
  import { apiClient } from '$lib/api/client';
  import * as m from '$lib/paraglide/messages';

  let {
    projectId,
    annotationProjectId,
    annotationProjectName,
    isOpen = false,
    onClose,
  }: {
    projectId: string;
    annotationProjectId: string;
    annotationProjectName: string;
    isOpen?: boolean;
    onClose: () => void;
  } = $props();

  type ExportFormat = 'json' | 'csv';

  let selectedFormat: ExportFormat = $state('json');
  let includeRejected = $state(false);
  let isExporting = $state(false);

  function getExportUrl(): string {
    const params = new URLSearchParams();
    params.set('format', selectedFormat);
    if (includeRejected) params.set('include_rejected', 'true');
    return `/web-api/v1/projects/${projectId}/annotation-projects/${annotationProjectId}/export?${params}`;
  }

  async function startExport() {
    isExporting = true;

    try {
      const response = await apiClient.requestRaw(getExportUrl());
      if (!response.ok) throw new Error(`Export failed: ${response.status}`);

      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      const safeName = annotationProjectName.replace(/\s+/g, '_') || 'annotations';
      link.download = `${safeName}_export.${selectedFormat}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
      onClose();
    } finally {
      isExporting = false;
    }
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && isOpen) {
      onClose();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if isOpen}
  <!-- svelte-ignore a11y-click-events-have-key-events -->
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div class="modal-overlay" onclick={onClose}>
    <div class="modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="export-dialog-title" tabindex="-1">
      <div class="modal-header">
        <h3 id="export-dialog-title">{m.annotation_export_title()}</h3>
        <button type="button" class="close-btn" onclick={onClose} aria-label={m.annotation_export_close_aria()}>
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <line x1="18" y1="6" x2="6" y2="18" stroke-width="2" />
            <line x1="6" y1="6" x2="18" y2="18" stroke-width="2" />
          </svg>
        </button>
      </div>

      <div class="modal-body">
        <p class="description">
          {m.annotation_export_description({ name: annotationProjectName || m.annotation_export_fallback_name() })}
        </p>

        <div class="field-group">
          <label class="field-label" for="export-format">{m.annotation_export_format_legend()}</label>
          <select id="export-format" class="field-select" bind:value={selectedFormat}>
            <option value="json">JSON</option>
            <option value="csv">CSV</option>
          </select>
        </div>

        <div class="export-options">
          <label class="option-item">
            <input type="checkbox" bind:checked={includeRejected} />
            <div class="option-content">
              <span class="option-label">{m.annotation_export_include_rejected_label()}</span>
              <span class="option-hint">{m.annotation_export_include_rejected_hint()}</span>
            </div>
          </label>
        </div>

        <div class="export-info">
          <h4>{m.annotation_export_contents_heading()}</h4>
          <ul>
            <li>{m.annotation_export_contents_clip_annotations()}</li>
            <li>{m.annotation_export_contents_sound_events()}</li>
            <li>{m.annotation_export_contents_metadata()}</li>
            {#if includeRejected}
              <li>{m.annotation_export_contents_rejected()}</li>
            {/if}
          </ul>
        </div>
      </div>

      <div class="modal-footer">
        <button type="button" class="btn-secondary" onclick={onClose} disabled={isExporting}>
          {m.annotation_export_cancel()}
        </button>
        <button
          type="button"
          class="btn-primary"
          onclick={startExport}
          disabled={isExporting}
        >
          {#if isExporting}
            <svg class="spinner" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" opacity="0.25" />
              <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            {m.annotation_export_exporting()}
          {:else}
            <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke-width="2" />
              <polyline points="7 10 12 15 17 10" stroke-width="2" />
              <line x1="12" y1="15" x2="12" y2="3" stroke-width="2" />
            </svg>
            {m.annotation_export_button()}
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
    background: rgb(var(--color-card-bg));
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

  .field-group {
    margin-bottom: 1.25rem;
  }

  .field-label {
    display: block;
    font-size: 0.875rem;
    font-weight: 500;
    color: #374151;
    margin-bottom: 0.375rem;
  }

  .field-select {
    width: 100%;
    padding: 0.5rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    color: #374151;
    background: rgb(var(--color-card-bg));
    cursor: pointer;
  }

  .field-select:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
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
    flex-shrink: 0;
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
    color: #6b7280;
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
    background: rgb(var(--color-card-bg));
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
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
</style>
