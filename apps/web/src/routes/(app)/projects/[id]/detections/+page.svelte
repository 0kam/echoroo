<script lang="ts">
  /**
   * Detections page - species detection summary for a project.
   * Lists all detected species with review progress and links to per-species views.
   */

  import { page } from '$app/stores';
  import SpeciesListView from '$lib/components/detection/SpeciesListView.svelte';

  $: projectId = $page.params.id as string;
</script>

<svelte:head>
  <title>Detections | Project</title>
</svelte:head>

<div class="mx-auto max-w-4xl px-6 py-8">
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
    <SpeciesListView {projectId} />
  {/if}
</div>
