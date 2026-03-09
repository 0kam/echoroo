<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import RecordingList from '$lib/components/data/RecordingList.svelte';

  const projectId = $derived(page.params.id);
  const datasetId = $derived(page.url.searchParams.get('dataset') ?? undefined);
  const siteId = $derived(page.url.searchParams.get('site') ?? undefined);

  function handleSelect(recordingId: string) {
    goto(localizeHref(`/projects/${projectId}/recordings/${recordingId}`));
  }
</script>

<svelte:head>
  <title>{m.recording_list_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-7xl px-6 py-8">
  <!-- Page header -->
  <div class="mb-6 flex items-start justify-between">
    <div>
      <nav class="mb-2 flex items-center gap-2 text-sm text-stone-500">
        <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-stone-900">{m.recording_list_breadcrumb_project()}</a>
        <span>/</span>
        <span class="font-medium text-stone-900">{m.recording_list_breadcrumb_recordings()}</span>
      </nav>
      <h1 class="text-2xl font-bold text-stone-900">{m.recording_list_heading()}</h1>
      {#if datasetId}
        <p class="mt-1 text-sm text-stone-500">{m.recording_list_filtered_by_dataset()}</p>
      {:else if siteId}
        <p class="mt-1 text-sm text-stone-500">{m.recording_list_filtered_by_site()}</p>
      {:else}
        <p class="mt-1 text-sm text-stone-500">{m.recording_list_all_recordings()}</p>
      {/if}
    </div>
  </div>

  {#if projectId}
    <RecordingList {projectId} {datasetId} {siteId} onSelect={handleSelect} />
  {/if}
</div>
