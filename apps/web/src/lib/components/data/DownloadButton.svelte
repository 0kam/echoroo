<script lang="ts">
  /**
   * DownloadButton component for downloading files.
   */

  interface Props {
    url: string;
    filename: string;
    label?: string;
    disabled?: boolean;
    variant?: 'primary' | 'secondary';
  }

  let { url, filename, label = 'Download', disabled = false, variant = 'secondary' }: Props = $props();

  let isDownloading = $state(false);

  async function download() {
    if (disabled || isDownloading) return;

    isDownloading = true;

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
  onclick={download}
  disabled={disabled || isDownloading}
  class="inline-flex items-center gap-2 whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium transition-all disabled:cursor-not-allowed disabled:opacity-50
    {variant === 'primary' ? 'border-0 bg-blue-600 text-white hover:bg-blue-700' : 'border border-gray-300 bg-gray-100 text-gray-700 hover:bg-gray-200'}"
>
  {#if isDownloading}
    <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" opacity="0.25"></circle>
      <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
    </svg>
    Downloading...
  {:else}
    <svg class="h-4 w-4 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke-width="2" />
      <polyline points="7 10 12 15 17 10" stroke-width="2" />
      <line x1="12" y1="15" x2="12" y2="3" stroke-width="2" />
    </svg>
    {label}
  {/if}
</button>
