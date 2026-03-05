<script lang="ts">
  /**
   * Detections page - species detection summary for a project.
   *
   * Provides two views:
   * - "Species List": paginated list of detected species with review progress
   * - "Activity Patterns": polar heatmap grid showing hourly detection activity
   */

  import { page } from '$app/stores';
  import { createQuery } from '@tanstack/svelte-query';
  import { fetchTemporalData } from '$lib/api/detections';
  import SpeciesListView from '$lib/components/detection/SpeciesListView.svelte';
  import DetectionVisualizationPanel from '$lib/components/detection/DetectionVisualizationPanel.svelte';

  $: projectId = $page.params.id as string;

  type Tab = 'species-list' | 'activity-patterns';
  let activeTab: Tab = 'species-list';

  // Lazy-load temporal data only when the "Activity Patterns" tab is selected
  $: temporalQuery = createQuery({
    queryKey: ['temporal-data', projectId],
    queryFn: () => fetchTemporalData(projectId),
    enabled: !!projectId && activeTab === 'activity-patterns',
  });

  $: temporalSpecies = $temporalQuery.data?.species ?? [];
</script>

<svelte:head>
  <title>Detections | Project</title>
</svelte:head>

<div class="mx-auto max-w-7xl px-6 py-8">
  <!-- Page header -->
  <div class="mb-6">
    <nav class="mb-2 flex items-center gap-2 text-sm text-gray-500">
      <a href="/projects/{projectId}" class="hover:text-gray-900">Project</a>
      <span>/</span>
      <span class="font-medium text-gray-900">Detections</span>
    </nav>
    <h1 class="text-2xl font-bold text-gray-900">Detections</h1>
    <p class="mt-1 text-sm text-gray-500">
      Review species detections and confirm or reject automated results.
    </p>
  </div>

  {#if projectId}
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
          Species List
        </button>
        <button
          type="button"
          on:click={() => (activeTab = 'activity-patterns')}
          class="whitespace-nowrap border-b-2 pb-3 text-sm font-medium transition-colors focus:outline-none {activeTab === 'activity-patterns'
            ? 'border-emerald-500 text-emerald-600'
            : 'border-transparent text-stone-500 hover:border-stone-300 hover:text-stone-700'}"
          aria-current={activeTab === 'activity-patterns' ? 'page' : undefined}
        >
          Activity Patterns
        </button>
      </nav>
    </div>

    <!-- Tab content -->
    {#if activeTab === 'species-list'}
      <div class="max-w-4xl">
        <SpeciesListView {projectId} />
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
            <span class="text-sm">Loading activity patterns...</span>
          </div>
        </div>
      {:else if $temporalQuery.isError}
        <div class="rounded-lg border border-red-200 bg-red-50 px-4 py-6 text-center">
          <p class="text-sm font-medium text-red-700">Failed to load activity patterns</p>
          <p class="mt-1 text-xs text-red-500">
            {$temporalQuery.error?.message ?? 'An unexpected error occurred'}
          </p>
          <button
            type="button"
            on:click={() => $temporalQuery.refetch()}
            class="mt-3 rounded-md bg-red-100 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-200"
          >
            Retry
          </button>
        </div>
      {:else}
        <DetectionVisualizationPanel species={temporalSpecies} />
      {/if}
    {/if}
  {/if}
</div>
