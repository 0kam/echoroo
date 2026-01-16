<script lang="ts">
  /**
   * DownloadButton component for downloading files.
   */

  export let url: string;
  export let filename: string;
  export let label: string = 'Download';
  export let disabled: boolean = false;
  export let variant: 'primary' | 'secondary' = 'secondary';

  let isDownloading = false;

  async function download() {
    if (disabled || isDownloading) return;

    isDownloading = true;

    // Trigger download via link
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    setTimeout(() => {
      isDownloading = false;
    }, 500);
  }
</script>

<button
  type="button"
  on:click={download}
  disabled={disabled || isDownloading}
  class="download-button"
  class:primary={variant === 'primary'}
  class:secondary={variant === 'secondary'}
>
  {#if isDownloading}
    <svg class="spinner" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" opacity="0.25" />
      <path
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
    Downloading...
  {:else}
    <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke-width="2" />
      <polyline points="7 10 12 15 17 10" stroke-width="2" />
      <line x1="12" y1="15" x2="12" y2="3" stroke-width="2" />
    </svg>
    {label}
  {/if}
</button>

<style>
  .download-button {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.625rem 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
    white-space: nowrap;
  }

  .download-button.primary {
    background: #3b82f6;
    color: white;
    border: none;
  }

  .download-button.primary:hover:not(:disabled) {
    background: #2563eb;
  }

  .download-button.secondary {
    background: #f3f4f6;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .download-button.secondary:hover:not(:disabled) {
    background: #e5e7eb;
  }

  .download-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .icon,
  .spinner {
    width: 18px;
    height: 18px;
    flex-shrink: 0;
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
