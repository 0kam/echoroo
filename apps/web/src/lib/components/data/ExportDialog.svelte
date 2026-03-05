<script lang="ts">
  /**
   * ExportDialog component for exporting datasets in CamtrapDP format.
   */

  import * as m from '$lib/paraglide/messages';

  interface Props {
    projectId: string;
    datasetId: string;
    datasetName: string;
    isOpen?: boolean;
    onClose: () => void;
  }

  let { projectId, datasetId, datasetName, isOpen = false, onClose }: Props = $props();

  let includeAudio = $state(false);
  let isExporting = $state(false);

  function getExportUrl(): string {
    const params = new URLSearchParams();
    if (includeAudio) params.append('include_audio', 'true');
    const queryString = params.toString();
    return `/api/v1/projects/${projectId}/datasets/${datasetId}/export${queryString ? `?${queryString}` : ''}`;
  }

  async function startExport() {
    isExporting = true;

    const link = document.createElement('a');
    link.href = getExportUrl();
    link.download = `${datasetName.replace(/\s+/g, '_')}_export.zip`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

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

<svelte:window onkeydown={handleKeydown} />

{#if isOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    onclick={onClose}
    role="dialog"
    aria-modal="true"
    aria-labelledby="export-dialog-title"
    tabindex="-1"
  >
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div
      class="w-full max-w-lg overflow-y-auto rounded-lg bg-white shadow-xl"
      onclick={(e) => e.stopPropagation()}
      role="document"
    >
      <!-- Header -->
      <div class="flex items-center justify-between border-b border-gray-200 px-6 py-4">
        <h3 id="export-dialog-title" class="m-0 text-lg font-semibold text-gray-900">{m.data_export_title()}</h3>
        <button
          type="button"
          onclick={onClose}
          aria-label="Close"
          class="rounded p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
        >
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <line x1="18" y1="6" x2="6" y2="18" stroke-width="2" />
            <line x1="6" y1="6" x2="18" y2="18" stroke-width="2" />
          </svg>
        </button>
      </div>

      <!-- Body -->
      <div class="p-6">
        <p class="mb-6 text-sm leading-relaxed text-gray-500">
          Export <strong class="text-gray-900">"{datasetName}"</strong> in CamtrapDP format. This includes metadata files
          (deployments.csv, media.csv) and a datapackage.json file.
        </p>

        <!-- Options -->
        <div class="mb-6">
          <label class="flex cursor-pointer items-start gap-3 rounded-lg border border-gray-200 p-4 transition-colors hover:bg-gray-50">
            <input type="checkbox" bind:checked={includeAudio} class="mt-0.5 h-4 w-4 cursor-pointer" />
            <div class="flex flex-col gap-0.5">
              <span class="text-sm font-medium text-gray-900">{m.data_export_include_audio_label()}</span>
              <span class="text-xs text-amber-600">{m.data_export_audio_warning()}</span>
            </div>
          </label>
        </div>

        <!-- Export info -->
        <div class="rounded-lg border border-gray-200 bg-gray-50 p-4">
          <h4 class="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">{m.data_export_contents_heading()}</h4>
          <ul class="m-0 pl-5 text-sm text-gray-600">
            <li class="mb-1"><code class="rounded bg-gray-200 px-1 py-0.5 font-mono text-xs">datapackage.json</code> - {m.data_export_datapackage_desc()}</li>
            <li class="mb-1"><code class="rounded bg-gray-200 px-1 py-0.5 font-mono text-xs">deployments.csv</code> - {m.data_export_deployments_desc()}</li>
            <li class="mb-1"><code class="rounded bg-gray-200 px-1 py-0.5 font-mono text-xs">media.csv</code> - {m.data_export_media_desc()}</li>
            {#if includeAudio}
              <li><code class="rounded bg-gray-200 px-1 py-0.5 font-mono text-xs">data/</code> - Audio files</li>
            {/if}
          </ul>
        </div>
      </div>

      <!-- Footer -->
      <div class="flex justify-end gap-3 rounded-b-lg border-t border-gray-200 bg-gray-50 px-6 py-4">
        <button
          type="button"
          onclick={onClose}
          disabled={isExporting}
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.data_export_cancel()}
        </button>
        <button
          type="button"
          onclick={startExport}
          disabled={isExporting}
          class="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {#if isExporting}
            <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" opacity="0.25"></circle>
              <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            {m.data_export_exporting()}
          {:else}
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke-width="2" />
              <polyline points="7 10 12 15 17 10" stroke-width="2" />
              <line x1="12" y1="15" x2="12" y2="3" stroke-width="2" />
            </svg>
            {m.data_export_button()}
          {/if}
        </button>
      </div>
    </div>
  </div>
{/if}
