<script lang="ts">
  /**
   * Detections page - species detection summary for a project.
   *
   * Provides two views:
   * - "Species List": paginated list of detected species with review progress
   * - "Activity Patterns": polar heatmap grid showing hourly detection activity
   *
   * Includes a Run selector to filter results by a specific MLAnalysis run.
   */

  import { page } from '$app/stores';
  import { createQuery } from '@tanstack/svelte-query';
  import { fetchTemporalData } from '$lib/api/detections';
  import { fetchDetectionRuns } from '$lib/api/detection-runs';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import SpeciesListView from '$lib/components/detection/SpeciesListView.svelte';
  import DetectionVisualizationPanel from '$lib/components/detection/DetectionVisualizationPanel.svelte';

  $: projectId = $page.params.id as string;
  $: locale = getLocale();

  type Tab = 'species-list' | 'activity-patterns';
  let activeTab: Tab = 'species-list';

  // Selected detection run ID (undefined = all runs)
  let selectedRunId: string | undefined = undefined;
  let runSelectorInitialized = false;

  // Fetch completed detection runs for the selector
  $: runsQuery = createQuery({
    queryKey: ['detection-runs', projectId],
    queryFn: () => fetchDetectionRuns(projectId),
    enabled: !!projectId,
  });

  // Filter to only COMPLETED runs, sorted newest first
  $: completedRuns = ($runsQuery.data?.items ?? []).filter((r) => r.status === 'completed');

  // Auto-select the most recent run once loaded
  $: if (!runSelectorInitialized && completedRuns.length > 0) {
    const firstRun = completedRuns[0];
    if (firstRun) {
      selectedRunId = firstRun.id;
    }
    runSelectorInitialized = true;
  }

  // Format a run label for display in the selector
  function formatRunLabel(run: { model_name: string; model_version: string; created_at: string; annotation_count: number }): string {
    const date = new Date(run.created_at).toLocaleDateString(locale === 'ja' ? 'ja-JP' : 'en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
    const version = run.model_version.replace(/^v/, '');
    return `${run.model_name} v${version} - ${date} (${run.annotation_count} ${locale === 'ja' ? '件の検出' : 'detections'})`;
  }

  // Lazy-load temporal data only when the "Activity Patterns" tab is selected
  $: temporalQuery = createQuery({
    queryKey: ['temporal-data', projectId, locale, selectedRunId],
    queryFn: () => fetchTemporalData(projectId, undefined, locale, selectedRunId),
    enabled: !!projectId && activeTab === 'activity-patterns',
  });

  $: temporalSpecies = $temporalQuery.data?.species ?? [];
</script>

<svelte:head>
  <title>{m.detection_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-7xl px-6 py-8">
  <!-- Page header -->
  <div class="mb-6">
    <nav class="mb-2 flex items-center gap-2 text-sm text-stone-500">
      <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-stone-900">{m.detection_breadcrumb_project()}</a>
      <span>/</span>
      <span class="font-medium text-stone-900">{m.detection_breadcrumb_detections()}</span>
    </nav>
    <h1 class="text-2xl font-bold text-stone-900">{m.detection_heading()}</h1>
    <p class="mt-1 text-sm text-stone-500">
      {m.detection_description()}
    </p>
  </div>

  {#if projectId}
    <!-- Run selector -->
    <div class="mb-6 flex items-center gap-3 rounded-lg border border-stone-200 bg-stone-50 px-4 py-3">
      <label for="run-selector" class="shrink-0 text-sm font-medium text-stone-600">
        {m.detection_run_selector_label()}:
      </label>
      {#if $runsQuery.isLoading}
        <span class="text-sm text-stone-400">{m.detection_run_loading()}</span>
      {:else if completedRuns.length === 0}
        <span class="text-sm text-stone-400">{m.detection_run_no_runs()}</span>
      {:else}
        <select
          id="run-selector"
          bind:value={selectedRunId}
          class="min-w-0 flex-1 rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 sm:max-w-sm"
        >
          {#each completedRuns as run (run.id)}
            <option value={run.id}>{formatRunLabel(run)}</option>
          {/each}
        </select>
      {/if}
    </div>

    <!-- Tab navigation -->
    <div class="mb-6 border-b border-stone-200">
      <nav class="-mb-px flex gap-6" aria-label="Detection views">
        <button
          type="button"
          on:click={() => (activeTab = 'species-list')}
          class="whitespace-nowrap border-b-2 pb-3 text-sm font-medium transition-colors focus:outline-none {activeTab === 'species-list'
            ? 'border-emerald-500 text-emerald-600'
            : 'border-transparent text-stone-500 hover:border-stone-300 hover:text-stone-700'}"
          aria-current={activeTab === 'species-list' ? 'page' : undefined}
        >
          {m.detection_tab_species_list()}
        </button>
        <button
          type="button"
          on:click={() => (activeTab = 'activity-patterns')}
          class="whitespace-nowrap border-b-2 pb-3 text-sm font-medium transition-colors focus:outline-none {activeTab === 'activity-patterns'
            ? 'border-emerald-500 text-emerald-600'
            : 'border-transparent text-stone-500 hover:border-stone-300 hover:text-stone-700'}"
          aria-current={activeTab === 'activity-patterns' ? 'page' : undefined}
        >
          {m.detection_tab_activity_patterns()}
        </button>
      </nav>
    </div>

    <!-- Tab content -->
    {#if activeTab === 'species-list'}
      <div class="max-w-4xl">
        <SpeciesListView {projectId} detectionRunId={selectedRunId} />
      </div>
    {:else}
      <!-- Activity Patterns tab -->
      {#if $temporalQuery.isLoading}
        <div class="flex items-center justify-center py-16">
          <div class="flex items-center gap-3 text-stone-500">
            <svg class="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span class="text-sm">{m.detection_loading_activity()}</span>
          </div>
        </div>
      {:else if $temporalQuery.isError}
        <div class="rounded-lg border border-red-200 bg-red-50 px-4 py-6 text-center">
          <p class="text-sm font-medium text-red-700">{m.detection_activity_load_error()}</p>
          <p class="mt-1 text-xs text-red-500">
            {$temporalQuery.error?.message ?? m.common_error_unexpected()}
          </p>
          <button
            type="button"
            on:click={() => $temporalQuery.refetch()}
            class="mt-3 rounded-md bg-red-100 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-200"
          >
            {m.detection_retry()}
          </button>
        </div>
      {:else}
        <DetectionVisualizationPanel species={temporalSpecies} />
      {/if}
    {/if}
  {/if}
</div>
