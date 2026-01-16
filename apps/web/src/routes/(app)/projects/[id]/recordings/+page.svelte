<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import RecordingList from '$lib/components/data/RecordingList.svelte';

  $: projectId = $page.params.id;
  $: datasetId = $page.url.searchParams.get('dataset') ?? undefined;
  $: siteId = $page.url.searchParams.get('site') ?? undefined;

  function handleSelect(recordingId: string) {
    goto(`/projects/${projectId}/recordings/${recordingId}`);
  }
</script>

<div class="recordings-page">
  <div class="page-header">
    <div>
      <h1 class="page-title">Recordings</h1>
      {#if datasetId}
        <p class="page-subtitle">Filtered by dataset</p>
      {:else if siteId}
        <p class="page-subtitle">Filtered by site</p>
      {/if}
    </div>
  </div>

  {#if projectId}
    <RecordingList {projectId} {datasetId} {siteId} onSelect={handleSelect} />
  {/if}
</div>

<style>
  .recordings-page {
    padding: 2rem;
    max-width: 1600px;
    margin: 0 auto;
  }

  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 2rem;
  }

  .page-title {
    margin: 0;
    font-size: 1.875rem;
    font-weight: 700;
    color: #111827;
  }

  .page-subtitle {
    margin: 0.5rem 0 0;
    font-size: 0.875rem;
    color: #6b7280;
  }
</style>
