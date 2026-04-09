<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { getLocale } from '$lib/paraglide/runtime';
  import { fetchDatasetStatistics } from '$lib/api/datasets';

  interface Props {
    projectId: string;
    datasetId: string;
  }

  let { projectId, datasetId }: Props = $props();

  const statsQuery = $derived(
    createQuery({
      queryKey: ['dataset-statistics', projectId, datasetId],
      queryFn: () => fetchDatasetStatistics(projectId, datasetId),
    })
  );

  function formatDuration(seconds: number): string {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    if (hours > 0) {
      return `${hours}h ${minutes}m ${secs}s`;
    } else if (minutes > 0) {
      return `${minutes}m ${secs}s`;
    } else {
      return `${secs}s`;
    }
  }

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString(getLocale());
  }

  function getMaxValue(obj: Record<string | number, number>): number {
    return Math.max(...Object.values(obj), 1);
  }
</script>

<div class="rounded-lg border border-card bg-surface-card p-6">
  <h3 class="mb-6 text-base font-semibold text-stone-900">Statistics</h3>

  {#if $statsQuery.isLoading}
    <div class="flex items-center justify-center py-8 text-sm text-stone-500">
      <svg class="mr-2 h-4 w-4 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      Loading statistics...
    </div>
  {:else if $statsQuery.isError}
    <div class="rounded-md bg-red-50 px-4 py-3 text-sm text-red-600">
      Error: {$statsQuery.error?.message}
    </div>
  {:else if $statsQuery.data}
    {@const stats = $statsQuery.data}

    <!-- Summary cards -->
    <div class="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div class="rounded-md border border-stone-200 bg-stone-50 p-4">
        <div class="mb-1 text-xs font-medium uppercase tracking-wider text-stone-500">Recordings</div>
        <div class="text-2xl font-semibold text-stone-900">{stats.recording_count.toLocaleString(getLocale())}</div>
      </div>

      <div class="rounded-md border border-stone-200 bg-stone-50 p-4">
        <div class="mb-1 text-xs font-medium uppercase tracking-wider text-stone-500">Total Duration</div>
        <div class="text-2xl font-semibold text-stone-900">{formatDuration(stats.total_duration)}</div>
      </div>

      {#if stats.date_range}
        <div class="rounded-md border border-stone-200 bg-stone-50 p-4">
          <div class="mb-1 text-xs font-medium uppercase tracking-wider text-stone-500">Date Range</div>
          <div class="text-sm font-medium text-stone-900 leading-relaxed">
            {formatDate(stats.date_range.start)}<br />to<br />{formatDate(stats.date_range.end)}
          </div>
        </div>
      {/if}
    </div>

    <!-- Distributions -->
    <div class="mb-6 grid grid-cols-1 gap-6 sm:grid-cols-2">
      <!-- Sample rate distribution -->
      {#if Object.keys(stats.samplerate_distribution).length > 0}
        <div class="rounded-md bg-stone-50 p-4">
          <h4 class="mb-3 text-sm font-semibold text-stone-700">Sample Rates</h4>
          <div class="flex flex-col gap-2">
            {#each Object.entries(stats.samplerate_distribution) as [samplerate, count]}
              {@const maxCount = getMaxValue(stats.samplerate_distribution)}
              {@const percentage = (count / maxCount) * 100}
              <div class="grid items-center gap-2" style="grid-template-columns: 80px 1fr">
                <div class="text-right text-xs font-medium text-stone-600">{parseInt(samplerate).toLocaleString(getLocale())} Hz</div>
                <div class="flex items-center gap-2">
                  <div class="h-5 rounded bg-primary-500 transition-all duration-300" style="width: {percentage}%; min-width: 2px;"></div>
                  <span class="whitespace-nowrap text-xs text-stone-500">{count.toLocaleString(getLocale())}</span>
                </div>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Format distribution -->
      {#if Object.keys(stats.format_distribution).length > 0}
        <div class="rounded-md bg-stone-50 p-4">
          <h4 class="mb-3 text-sm font-semibold text-stone-700">File Formats</h4>
          <div class="flex flex-col gap-2">
            {#each Object.entries(stats.format_distribution) as [format, count]}
              {@const maxCount = getMaxValue(stats.format_distribution)}
              {@const percentage = (count / maxCount) * 100}
              <div class="grid items-center gap-2" style="grid-template-columns: 80px 1fr">
                <div class="text-right text-xs font-medium text-stone-600">{format.toUpperCase()}</div>
                <div class="flex items-center gap-2">
                  <div class="h-5 rounded bg-primary-500 transition-all duration-300" style="width: {percentage}%; min-width: 2px;"></div>
                  <span class="whitespace-nowrap text-xs text-stone-500">{count.toLocaleString(getLocale())}</span>
                </div>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </div>

    <!-- Recordings by date -->
    {#if stats.recordings_by_date.length > 0}
      {@const maxCount = Math.max(...stats.recordings_by_date.map((d) => d.count), 1)}
      <div class="mb-6">
        <h4 class="mb-3 text-sm font-semibold text-stone-700">Recordings by Date</h4>
        <div class="flex h-36 items-end gap-0.5 overflow-x-auto rounded-md bg-stone-50 p-3">
          {#each stats.recordings_by_date.slice(0, 30) as dateData}
            {@const percentage = (dateData.count / maxCount) * 100}
            <div
              class="flex min-w-[48px] flex-col items-center"
              title="{formatDate(dateData.date)}: {dateData.count} recording(s)"
            >
              <div
                class="w-full rounded-t bg-primary-500 transition-all duration-300"
                style="height: {percentage}%; min-height: 2px;"
              ></div>
              <div class="mt-1 text-[10px] text-stone-400" style="writing-mode: vertical-rl;">
                {formatDate(dateData.date)}
              </div>
            </div>
          {/each}
        </div>
        {#if stats.recordings_by_date.length > 30}
          <p class="mt-1 text-xs italic text-stone-400">Showing first 30 days</p>
        {/if}
      </div>
    {/if}

    <!-- Recordings by hour -->
    {#if stats.recordings_by_hour.length > 0}
      {@const maxCount = Math.max(...stats.recordings_by_hour.map((h) => h.count), 1)}
      <div>
        <h4 class="mb-3 text-sm font-semibold text-stone-700">Recordings by Hour of Day</h4>
        <div class="grid h-28 grid-cols-[repeat(24,1fr)] items-end gap-0.5 rounded-md bg-stone-50 p-3">
          {#each stats.recordings_by_hour as hourData}
            {@const percentage = (hourData.count / maxCount) * 100}
            <div class="flex h-full flex-col items-center">
              <div
                class="w-full cursor-pointer rounded-t bg-primary-500 transition-all duration-300 hover:bg-primary-600"
                style="height: {percentage}%; min-height: 2px;"
                title="{hourData.hour}:00 - {hourData.count} recording(s)"
              ></div>
              <div class="mt-auto pt-1 text-[9px] text-stone-400">{hourData.hour}</div>
            </div>
          {/each}
        </div>
      </div>
    {/if}
  {/if}
</div>
