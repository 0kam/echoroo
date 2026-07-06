<script lang="ts">
  /**
   * SearchSessionExportButton - Button to export a search session as a CSV file.
   *
   * Triggers a browser download of the session's results when clicked.
   */

  import * as m from '$lib/paraglide/messages';
  import { toastError } from '$lib/stores/toast';
  import { exportSearchSessionCSV } from '$lib/api/search';

  interface Props {
    projectId: string;
    sessionId: string;
    disabled?: boolean;
  }

  let { projectId, sessionId, disabled = false }: Props = $props();

  let isExporting = $state(false);

  async function handleExport() {
    isExporting = true;
    try {
      await exportSearchSessionCSV(projectId, sessionId);
    } catch (e) {
      console.error('Export failed:', e);
      toastError(e, m.search_export_failed());
    } finally {
      isExporting = false;
    }
  }
</script>

<button
  type="button"
  onclick={handleExport}
  disabled={disabled || isExporting}
  class="inline-flex items-center gap-1.5 rounded-lg border border-stone-300 bg-surface-card px-3 py-1.5 text-sm font-medium text-stone-700 shadow-sm transition hover:bg-stone-50 disabled:opacity-50"
>
  {#if isExporting}
    <!-- Spinner icon while exporting -->
    <svg class="h-4 w-4 animate-spin text-stone-400" fill="none" viewBox="0 0 24 24" aria-hidden="true">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
    </svg>
    {m.search_exporting()}
  {:else}
    <!-- Download icon -->
    <svg class="h-4 w-4 text-stone-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
      <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
    </svg>
    {m.search_export_csv()}
  {/if}
</button>
