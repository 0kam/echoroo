<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import RecordingList from '$lib/components/data/RecordingList.svelte';

  const projectId = $derived(page.params.id);
  const datasetId = $derived(page.url.searchParams.get('dataset') ?? undefined);
  const siteId = $derived(page.url.searchParams.get('site') ?? undefined);

  function handleSelect(recordingId: string) {
    goto(`/projects/${projectId}/recordings/${recordingId}`);
  }
</script>

<svelte:head>
  <title>Recordings | Project</title>
</svelte:head>

<div class="mx-auto max-w-7xl px-6 py-8">
  <!-- Page header -->
  <div class="mb-6 flex items-start justify-between">
    <div>
      <nav class="mb-2 flex items-center gap-2 text-sm text-gray-500">
        <a href="/projects/{projectId}" class="hover:text-gray-900">Project</a>
        <span>/</span>
        <span class="font-medium text-gray-900">Recordings</span>
      </nav>
      <h1 class="text-2xl font-bold text-gray-900">Recordings</h1>
      {#if datasetId}
        <p class="mt-1 text-sm text-gray-500">Filtered by dataset</p>
      {:else if siteId}
        <p class="mt-1 text-sm text-gray-500">Filtered by site</p>
      {:else}
        <p class="mt-1 text-sm text-gray-500">All recordings in this project</p>
      {/if}
    </div>
  </div>

  {#if projectId}
    <RecordingList {projectId} {datasetId} {siteId} onSelect={handleSelect} />
  {/if}
</div>
