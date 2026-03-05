<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchSite, updateSite, deleteSite } from '$lib/api/sites';
  import { localizeHref } from '$lib/paraglide/runtime';
  import { fetchDatasets } from '$lib/api/datasets';
  import type { SiteCreate } from '$lib/types/data';
  import SiteForm from '$lib/components/data/SiteForm.svelte';
  import DeleteConfirmDialog from '$lib/components/ui/DeleteConfirmDialog.svelte';
  import H3MapPicker from '$lib/components/map/H3MapPicker.svelte';
  import * as m from '$lib/paraglide/messages';

  const projectId = $derived($page.params.id as string);
  const siteId = $derived($page.params.siteId as string);

  const queryClient = useQueryClient();

  let isEditing = $state(false);
  let showDeleteConfirm = $state(false);

  const siteQuery = $derived(
    createQuery({
      queryKey: ['site', projectId, siteId],
      queryFn: () => fetchSite(projectId, siteId),
      enabled: !!projectId && !!siteId,
    })
  );

  const datasetsQuery = $derived(
    createQuery({
      queryKey: ['datasets', projectId, 'site', siteId],
      queryFn: () => fetchDatasets(projectId, { site_id: siteId, page_size: 10 }),
      enabled: !!projectId && !!siteId,
    })
  );

  const updateMutation = createMutation({
    mutationFn: (data: SiteCreate) => updateSite(projectId, siteId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['site', projectId, siteId] });
      queryClient.invalidateQueries({ queryKey: ['sites', projectId] });
      isEditing = false;
    },
  });

  const deleteMutation = createMutation({
    mutationFn: () => deleteSite(projectId, siteId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sites', projectId] });
      goto(localizeHref(`/projects/${projectId}/sites`));
    },
  });

  async function handleUpdateSubmit(data: SiteCreate) {
    await $updateMutation.mutateAsync(data);
  }

  function handleDeleteConfirm() {
    $deleteMutation.mutate();
    showDeleteConfirm = false;
  }

  function formatDuration(seconds: number): string {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
  }

  const deleteWarnings = $derived(
    $siteQuery.data
      ? [
          m.site_detail_delete_warning_datasets({ count: $siteQuery.data.dataset_count }),
          m.site_detail_delete_warning_recordings({ count: $siteQuery.data.recording_count }),
          m.site_detail_delete_warning_audio({ duration: formatDuration($siteQuery.data.total_duration) }),
        ]
      : []
  );
</script>

<svelte:head>
  <title>{m.site_detail_page_title({ name: $siteQuery.data?.name ?? 'Site' })}</title>
</svelte:head>

<div class="mx-auto max-w-4xl space-y-6 px-6 py-8">
  <!-- Breadcrumb -->
  <nav class="flex items-center gap-2 text-sm text-gray-500">
    <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-gray-900">{m.site_detail_breadcrumb_project()}</a>
    <span>/</span>
    <a href={localizeHref(`/projects/${projectId}/sites`)} class="hover:text-gray-900">{m.site_detail_breadcrumb_sites()}</a>
    <span>/</span>
    <span class="font-medium text-gray-900">{$siteQuery.data?.name ?? m.common_loading()}</span>
  </nav>

  {#if $siteQuery.isLoading}
    <div class="flex items-center justify-center py-12 text-sm text-gray-500">
      <svg class="mr-2 h-5 w-5 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      {m.site_detail_loading()}
    </div>
  {:else if $siteQuery.isError}
    <div class="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
      Error: {$siteQuery.error?.message}
    </div>
  {:else if $siteQuery.data}
    {#if isEditing}
      <div class="rounded-lg border border-gray-200 bg-white p-6">
        <div class="mb-4 flex items-center justify-between">
          <h2 class="text-lg font-semibold text-gray-900">{m.site_detail_edit_heading()}</h2>
          <button
            onclick={() => (isEditing = false)}
            class="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            aria-label={m.common_cancel()}
          >
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <line x1="18" y1="6" x2="6" y2="18" stroke-width="2" />
              <line x1="6" y1="6" x2="18" y2="18" stroke-width="2" />
            </svg>
          </button>
        </div>
        <SiteForm
          site={$siteQuery.data}
          onSubmit={handleUpdateSubmit}
          onCancel={() => (isEditing = false)}
        />
      </div>
    {:else}
      <!-- Site header -->
      <div class="flex items-start justify-between">
        <div>
          <h1 class="text-2xl font-bold text-gray-900">{$siteQuery.data.name}</h1>
          <code class="mt-1 inline-block rounded bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-500">
            {$siteQuery.data.h3_index}
          </code>
          {#if $siteQuery.data.latitude !== null && $siteQuery.data.longitude !== null}
            <p class="mt-1 text-sm text-gray-500">
              {$siteQuery.data.latitude?.toFixed(6)}, {$siteQuery.data.longitude?.toFixed(6)}
            </p>
          {/if}
        </div>
        <div class="flex gap-2">
          <button
            onclick={() => (isEditing = true)}
            class="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
          >
            {m.site_detail_edit_button()}
          </button>
          <button
            onclick={() => (showDeleteConfirm = true)}
            class="rounded-md border border-red-200 bg-white px-3 py-2 text-sm font-medium text-red-600 transition-colors hover:bg-red-50"
          >
            {m.site_detail_delete_button()}
          </button>
        </div>
      </div>

      <!-- Location map -->
      {#if $siteQuery.data.h3_index}
        <div class="rounded-lg border border-gray-200 bg-white p-4">
          <h2 class="mb-3 text-sm font-semibold text-gray-700">{m.site_detail_location_heading()}</h2>
          <H3MapPicker h3Index={$siteQuery.data.h3_index} readonly={true} />
        </div>
      {/if}

      <!-- Stats -->
      <div class="grid grid-cols-3 gap-4">
        <div class="rounded-lg border border-gray-200 bg-white p-5 text-center">
          <div class="text-2xl font-semibold text-gray-900">{$siteQuery.data.dataset_count}</div>
          <div class="mt-1 text-sm text-gray-500">{m.site_detail_stat_datasets()}</div>
        </div>
        <div class="rounded-lg border border-gray-200 bg-white p-5 text-center">
          <div class="text-2xl font-semibold text-gray-900">{$siteQuery.data.recording_count}</div>
          <div class="mt-1 text-sm text-gray-500">{m.site_detail_stat_recordings()}</div>
        </div>
        <div class="rounded-lg border border-gray-200 bg-white p-5 text-center">
          <div class="text-2xl font-semibold text-gray-900">{formatDuration($siteQuery.data.total_duration)}</div>
          <div class="mt-1 text-sm text-gray-500">{m.site_detail_stat_duration()}</div>
        </div>
      </div>

      <!-- Datasets at this site -->
      <section class="rounded-lg border border-gray-200 bg-white p-6">
        <div class="mb-4 flex items-center justify-between">
          <h2 class="text-base font-semibold text-gray-900">{m.site_detail_datasets_heading()}</h2>
          <a
            href={localizeHref(`/projects/${projectId}/datasets?site_id=${siteId}`)}
            class="text-sm font-medium text-blue-600 no-underline hover:underline"
          >
            {m.site_detail_view_all_datasets()}
          </a>
        </div>

        {#if $datasetsQuery.isLoading}
          <div class="py-4 text-center text-sm text-gray-400">{m.site_detail_loading_datasets()}</div>
        {:else if $datasetsQuery.data && $datasetsQuery.data.items.length > 0}
          <ul class="flex flex-col gap-2 p-0 list-none">
            {#each $datasetsQuery.data.items as dataset}
              <li>
                <a
                  href={localizeHref(`/projects/${projectId}/datasets/${dataset.id}`)}
                  class="flex items-center justify-between rounded-md border border-gray-100 p-3 no-underline transition-colors hover:bg-gray-50"
                >
                  <span class="text-sm font-medium text-gray-900">{dataset.name}</span>
                  <span class="text-xs text-gray-400">{dataset.processed_files} files</span>
                </a>
              </li>
            {/each}
          </ul>
          {#if $datasetsQuery.data.total > $datasetsQuery.data.items.length}
            <p class="mt-2 text-xs text-gray-400">
              {m.site_detail_showing({ showing: $datasetsQuery.data.items.length, total: $datasetsQuery.data.total })}
            </p>
          {/if}
        {:else}
          <p class="py-4 text-center text-sm text-gray-400">{m.site_detail_no_datasets()}</p>
        {/if}
      </section>

      <!-- Recordings quick link -->
      <div class="flex items-center justify-between rounded-lg border border-gray-200 bg-white p-5">
        <div>
          <h3 class="mb-0.5 text-base font-semibold text-gray-900">{m.site_detail_recordings_heading()}</h3>
          <p class="text-sm text-gray-500">{m.site_detail_recordings_description()}</p>
        </div>
        <a
          href={localizeHref(`/projects/${projectId}/recordings?site=${siteId}`)}
          class="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white no-underline transition-colors hover:bg-blue-700"
        >
          {m.site_detail_view_recordings()}
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
          </svg>
        </a>
      </div>
    {/if}
  {/if}
</div>

<DeleteConfirmDialog
  isOpen={showDeleteConfirm}
  title={m.site_detail_delete_title()}
  message={m.site_detail_delete_message({ name: $siteQuery.data?.name ?? '' })}
  warnings={deleteWarnings}
  confirmText={m.site_detail_delete_confirm()}
  isDeleting={$deleteMutation.isPending}
  onConfirm={handleDeleteConfirm}
  onCancel={() => (showDeleteConfirm = false)}
/>
