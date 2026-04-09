<script lang="ts">
  /**
   * Card component showing datetime parsing status for a dataset.
   * Displayed on the dataset detail page.
   */

  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages';
  import { fetchDatetimeConfig } from '$lib/api/datasets';
  import DatetimeConfigModal from './DatetimeConfigModal.svelte';

  interface Props {
    projectId: string;
    datasetId: string;
  }

  let { projectId, datasetId }: Props = $props();

  const queryClient = useQueryClient();
  const queryKey = $derived(['datetime-config', projectId, datasetId]);

  const configQuery = $derived(
    createQuery({
      queryKey: queryKey,
      queryFn: () => fetchDatetimeConfig(projectId, datasetId),
    })
  );

  let showModal = $state(false);

  function handleModalClose() {
    showModal = false;
    queryClient.invalidateQueries({ queryKey: queryKey });
  }

  const isConfigured = $derived(
    !!$configQuery.data?.datetime_pattern && !!$configQuery.data?.datetime_format
  );
</script>

<div class="rounded-lg border border-card bg-surface-card p-6">
  <div class="flex items-start justify-between gap-4">
    <div class="flex items-center gap-2">
      <!-- Clock icon -->
      <svg
        class="h-5 w-5 text-primary-500"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.75"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
      <div>
        <h3 class="text-base font-semibold text-stone-900">{m.datetime_config_title()}</h3>
        <p class="mt-0.5 text-sm text-stone-500">{m.datetime_config_description()}</p>
      </div>
    </div>

    <button
      onclick={() => (showModal = true)}
      class="flex-shrink-0 rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50"
    >
      {isConfigured ? m.datetime_config_reconfigure() : m.datetime_config_configure()}
    </button>
  </div>

  {#if $configQuery.isLoading}
    <div class="mt-4 flex items-center gap-2 text-sm text-stone-500">
      <svg class="h-4 w-4 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      {m.common_loading()}
    </div>
  {:else if $configQuery.isError}
    <div class="mt-4 text-sm text-red-600">
      {$configQuery.error?.message}
    </div>
  {:else if $configQuery.data}
    {@const summary = $configQuery.data.parse_summary}
    <div class="mt-4 flex flex-wrap items-center gap-3">
      {#if summary.success > 0}
        <span class="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400">
          <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
          {m.datetime_config_parsed({ count: summary.success })}
        </span>
      {/if}
      {#if summary.pending > 0}
        <span class="inline-flex items-center gap-1 rounded-full bg-yellow-100 px-2.5 py-0.5 text-xs font-medium text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400">
          <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          {m.datetime_config_pending({ count: summary.pending })}
        </span>
      {/if}
      {#if summary.failed > 0}
        <span class="inline-flex items-center gap-1 rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900/30 dark:text-red-400">
          <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18" stroke-width="2" />
            <line x1="6" y1="6" x2="18" y2="18" stroke-width="2" />
          </svg>
          {m.datetime_config_failed({ count: summary.failed })}
        </span>
      {/if}
      {#if summary.total === 0}
        <span class="text-sm text-stone-400">{m.datetime_config_no_recordings()}</span>
      {/if}
    </div>

    {#if isConfigured}
      <div class="mt-3 rounded-md bg-stone-50 px-3 py-2">
        <code class="text-xs text-stone-600">{$configQuery.data.datetime_format}</code>
      </div>
    {/if}
  {/if}
</div>

{#if showModal}
  <DatetimeConfigModal
    {projectId}
    {datasetId}
    currentPattern={$configQuery.data?.datetime_pattern ?? null}
    currentFormat={$configQuery.data?.datetime_format ?? null}
    currentTimezone={$configQuery.data?.datetime_timezone ?? null}
    sampleFilenames={$configQuery.data?.sample_filenames ?? []}
    onClose={handleModalClose}
  />
{/if}
