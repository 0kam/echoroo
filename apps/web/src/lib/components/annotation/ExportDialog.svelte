<script lang="ts">
  import { fetchWithErrorHandling } from '$lib/api/errors';
  import type { ExportFormat } from '$lib/types/annotation';
  import * as m from '$lib/paraglide/messages';

  export let isOpen: boolean = false;
  export let projectId: string;
  export let annotationProjectId: string;
  export let annotationProjectName: string = '';
  export let onClose: () => void;

  interface FormatOption {
    value: ExportFormat;
    label: string;
    description: string;
  }

  const FORMAT_OPTIONS: FormatOption[] = [
    {
      value: 'json',
      label: 'JSON (Full metadata)',
      description: 'Complete annotation data with project info',
    },
    {
      value: 'csv',
      label: 'CSV (Raven-compatible)',
      description: 'Tab-separated, compatible with Raven Pro',
    },
    {
      value: 'aoef',
      label: 'AOEF (soundevent)',
      description: 'Audio Object Event Format for soundevent library',
    },
  ];

  let selectedFormat: ExportFormat = 'json';
  let isExporting = false;
  let exportError = '';

  function handleOverlayClick(event: MouseEvent) {
    if (event.target === event.currentTarget) {
      handleClose();
    }
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      handleClose();
    }
  }

  function handleClose() {
    if (isExporting) return;
    exportError = '';
    onClose();
  }

  async function handleExport() {
    exportError = '';
    isExporting = true;

    try {
      const url = `/api/v1/projects/${projectId}/annotation-projects/${annotationProjectId}/export?format=${selectedFormat}`;
      const response = await fetchWithErrorHandling(url, { credentials: 'include' });

      let blob: Blob;
      let filename: string;

      if (selectedFormat === 'csv') {
        const text = await response.text();
        blob = new Blob([text], { type: 'text/csv' });
        filename = `${annotationProjectName || 'annotations'}_export.csv`;
      } else {
        const json = await response.json();
        blob = new Blob([JSON.stringify(json, null, 2)], { type: 'application/json' });
        filename = `${annotationProjectName || 'annotations'}_export.${selectedFormat === 'aoef' ? 'aoef.json' : 'json'}`;
      }

      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = filename;
      link.click();
      URL.revokeObjectURL(link.href);

      handleClose();
    } catch (error) {
      exportError = error instanceof Error ? error.message : m.annotation_export_error();
    } finally {
      isExporting = false;
    }
  }
</script>

<svelte:window on:keydown={handleKeydown} />

{#if isOpen}
  <!-- svelte-ignore a11y-click-events-have-key-events -->
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <!-- svelte-ignore a11y_interactive_supports_focus -->
  <div
    class="overlay"
    on:click={handleOverlayClick}
    role="dialog"
    aria-modal="true"
    aria-labelledby="export-dialog-title"
    tabindex="-1"
  >
    <div class="dialog">
      <!-- Header -->
      <div class="dialog-header">
        <h2 class="dialog-title" id="export-dialog-title">{m.annotation_export_title()}</h2>
        <button
          type="button"
          class="close-btn"
          on:click={handleClose}
          disabled={isExporting}
          aria-label={m.annotation_export_close_aria()}
        >
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            aria-hidden="true"
            class="close-icon"
          >
            <path stroke-linecap="round" d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      </div>

      <!-- Body -->
      <div class="dialog-body">
        <!-- Format selector -->
        <fieldset class="format-fieldset">
          <legend class="format-legend">{m.annotation_export_format_legend()}</legend>
          <div class="format-options">
            {#each FORMAT_OPTIONS as option (option.value)}
              <label
                class="format-option"
                class:format-option--selected={selectedFormat === option.value}
              >
                <input
                  type="radio"
                  name="export-format"
                  value={option.value}
                  bind:group={selectedFormat}
                  class="format-radio"
                  disabled={isExporting}
                />
                <div class="format-option-content">
                  <span class="format-option-label">{option.label}</span>
                  <span class="format-option-description">{option.description}</span>
                </div>
              </label>
            {/each}
          </div>
        </fieldset>

        <!-- Error message -->
        {#if exportError}
          <div class="error-box" role="alert">
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              aria-hidden="true"
              class="error-icon"
            >
              <circle cx="8" cy="8" r="6" />
              <path stroke-linecap="round" d="M8 5v3.5M8 10.5v.5" />
            </svg>
            <p class="error-text">{exportError}</p>
          </div>
        {/if}
      </div>

      <!-- Footer -->
      <div class="dialog-footer">
        <button
          type="button"
          class="btn btn--cancel"
          on:click={handleClose}
          disabled={isExporting}
        >
          {m.annotation_export_cancel()}
        </button>
        <button
          type="button"
          class="btn btn--export"
          on:click={handleExport}
          disabled={isExporting}
          aria-busy={isExporting}
        >
          {#if isExporting}
            <svg class="spinner" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle
                cx="8"
                cy="8"
                r="6"
                stroke="currentColor"
                stroke-width="2"
                stroke-dasharray="28"
                stroke-dashoffset="10"
              />
            </svg>
            {m.annotation_export_exporting()}
          {:else}
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              aria-hidden="true"
              class="export-icon"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M8 2v8M5 7l3 3 3-3M2 12h12" />
            </svg>
            {m.annotation_export_button()}
          {/if}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  /* ---- Overlay ---- */
  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
    padding: 1rem;
  }

  /* ---- Dialog ---- */
  .dialog {
    background: #fff;
    border-radius: 0.5rem;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
    width: 100%;
    max-width: 28rem;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ---- Header ---- */
  .dialog-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1rem 1.25rem 0.875rem;
    border-bottom: 1px solid #e5e7eb;
  }

  .dialog-title {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: #111827;
  }

  .close-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.75rem;
    height: 1.75rem;
    border: none;
    background: transparent;
    border-radius: 0.375rem;
    cursor: pointer;
    color: #6b7280;
    padding: 0;
    transition: background 0.1s ease, color 0.1s ease;
  }

  .close-btn:hover:not(:disabled) {
    background: #f3f4f6;
    color: #111827;
  }

  .close-btn:focus-visible {
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
  }

  .close-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .close-icon {
    width: 1rem;
    height: 1rem;
  }

  /* ---- Body ---- */
  .dialog-body {
    padding: 1rem 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  /* ---- Format fieldset ---- */
  .format-fieldset {
    border: none;
    margin: 0;
    padding: 0;
  }

  .format-legend {
    font-size: 0.8125rem;
    font-weight: 500;
    color: #374151;
    margin-bottom: 0.625rem;
    padding: 0;
  }

  .format-options {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .format-option {
    display: flex;
    align-items: flex-start;
    gap: 0.625rem;
    padding: 0.625rem 0.75rem;
    border: 1.5px solid #e5e7eb;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: border-color 0.1s ease, background 0.1s ease;
    background: #fff;
  }

  .format-option:hover {
    border-color: #93c5fd;
    background: #eff6ff;
  }

  .format-option--selected {
    border-color: #2563eb;
    background: #eff6ff;
  }

  .format-radio {
    margin-top: 0.125rem;
    flex-shrink: 0;
    accent-color: #2563eb;
    cursor: pointer;
  }

  .format-radio:disabled {
    cursor: not-allowed;
  }

  .format-option-content {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    min-width: 0;
  }

  .format-option-label {
    font-size: 0.875rem;
    font-weight: 500;
    color: #111827;
  }

  .format-option-description {
    font-size: 0.75rem;
    color: #6b7280;
    line-height: 1.45;
  }

  /* ---- Error box ---- */
  .error-box {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    padding: 0.625rem 0.75rem;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 0.375rem;
  }

  .error-icon {
    width: 1rem;
    height: 1rem;
    flex-shrink: 0;
    color: #dc2626;
    margin-top: 0.0625rem;
  }

  .error-text {
    margin: 0;
    font-size: 0.8125rem;
    color: #dc2626;
    line-height: 1.45;
  }

  /* ---- Footer ---- */
  .dialog-footer {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    padding: 0.875rem 1.25rem 1rem;
    border-top: 1px solid #e5e7eb;
  }

  .btn {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.5rem 1rem;
    border: none;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    transition: background 0.1s ease, opacity 0.1s ease;
  }

  .btn:focus-visible {
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
  }

  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn--cancel {
    background: #f3f4f6;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .btn--cancel:hover:not(:disabled) {
    background: #e5e7eb;
  }

  .btn--export {
    background: #2563eb;
    color: #fff;
    min-width: 6.5rem;
    justify-content: center;
  }

  .btn--export:hover:not(:disabled) {
    background: #1d4ed8;
  }

  .export-icon {
    width: 0.875rem;
    height: 0.875rem;
  }

  /* ---- Spinner ---- */
  .spinner {
    width: 0.875rem;
    height: 0.875rem;
    animation: spin 0.75s linear infinite;
    flex-shrink: 0;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
