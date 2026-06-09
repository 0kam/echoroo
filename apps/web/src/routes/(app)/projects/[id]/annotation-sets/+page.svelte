<script lang="ts">
  /**
   * Annotation Sets list page.
   *
   * Displays every annotation set in the current project with status badges,
   * segment counts, and a simple progress bar. Rows link to the detail
   * (progress) page; a "New annotation set" button opens the create wizard.
   */
  import { page } from '$app/stores';
  import { createQuery } from '@tanstack/svelte-query';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import { listAnnotationSets } from '$lib/api/annotation-sets';
  import type { AnnotationSet, AnnotationSetStatus } from '$lib/types/annotation-set';

  const projectId = $derived($page.params.id as string);

  const setsQuery = $derived(
    createQuery({
      queryKey: ['annotation-sets', projectId],
      queryFn: () => listAnnotationSets({ project_id: projectId, page_size: 100 }),
      enabled: !!projectId,
      refetchOnWindowFocus: false,
    }),
  );

  function statusLabel(status: AnnotationSetStatus): string {
    switch (status) {
      case 'sampling':
        return m.annotation_sets_status_sampling();
      case 'ready':
        return m.annotation_sets_status_ready();
      case 'in_progress':
        return m.annotation_sets_status_in_progress();
      case 'completed':
        return m.annotation_sets_status_completed();
    }
  }

  function statusClass(status: AnnotationSetStatus): string {
    switch (status) {
      case 'sampling':
        return 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300';
      case 'ready':
        return 'bg-primary-100 text-primary-800 dark:bg-primary-900/30 dark:text-primary-300';
      case 'in_progress':
        return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300';
      case 'completed':
        return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300';
    }
  }

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  }

  function detailHref(setId: string): string {
    return localizeHref(`/projects/${projectId}/annotation-sets/${setId}`);
  }

  /**
   * Real annotation progress as a percentage, matching the detail page's
   * formula: `annotated / total * 100` (0 when there are no segments yet).
   */
  function progressPercent(set: AnnotationSet): number {
    const p = set.progress;
    if (!p || p.total === 0) return 0;
    return Math.round((p.annotated / p.total) * 100);
  }
</script>

<svelte:head>
  <title>{m.annotation_sets_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-5xl px-4 py-6">
  <!-- Breadcrumb -->
  <nav class="mb-4 flex items-center gap-2 text-sm text-stone-500">
    <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-stone-900 dark:hover:text-stone-200">
      {m.search_breadcrumb_project()}
    </a>
    <span>/</span>
    <span class="font-medium text-stone-900 dark:text-stone-100">{m.annotation_sets_list_title()}</span>
  </nav>

  <div class="mb-6 flex items-start justify-between gap-4">
    <div>
      <h1 class="text-2xl font-bold text-stone-900 dark:text-stone-100">
        {m.annotation_sets_list_title()}
      </h1>
      <p class="mt-1 text-sm text-stone-500">{m.annotation_sets_list_description()}</p>
    </div>

    <a
      href={localizeHref(`/projects/${projectId}/annotation-sets/new`)}
      class="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700 dark:bg-primary-500 dark:hover:bg-primary-400"
    >
      <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
      </svg>
      {m.annotation_sets_list_create()}
    </a>
  </div>

  {#if $setsQuery.isLoading}
    <div class="flex items-center gap-2 text-sm text-stone-400">
      <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      {m.annotation_sets_list_loading()}
    </div>
  {:else if $setsQuery.isError}
    <div class="rounded-lg border border-danger/30 bg-danger-light p-4 text-sm text-danger">
      {m.annotation_sets_list_error()}
    </div>
  {:else if $setsQuery.data && $setsQuery.data.items.length === 0}
    <div class="rounded-xl border-2 border-dashed border-stone-200 bg-surface-card p-12 text-center dark:border-stone-700">
      <svg class="mx-auto h-12 w-12 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 17l3-3 3 3m-3-3V6m-5 15h10a2 2 0 002-2V7l-5-4H6a2 2 0 00-2 2v14a2 2 0 002 2z" />
      </svg>
      <h2 class="mt-4 text-base font-semibold text-stone-700 dark:text-stone-200">
        {m.annotation_sets_list_empty_title()}
      </h2>
      <p class="mt-1 text-sm text-stone-500">{m.annotation_sets_list_empty_description()}</p>
      <a
        href={localizeHref(`/projects/${projectId}/annotation-sets/new`)}
        class="mt-6 inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700 dark:bg-primary-500 dark:hover:bg-primary-400"
      >
        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
        </svg>
        {m.annotation_sets_list_create()}
      </a>
    </div>
  {:else if $setsQuery.data}
    <div class="overflow-hidden rounded-xl border border-card bg-surface-card shadow-sm">
      <table class="min-w-full divide-y divide-stone-200 dark:divide-stone-700">
        <thead class="bg-stone-50 text-left text-xs font-semibold uppercase tracking-wider text-stone-500 dark:bg-stone-800/40">
          <tr>
            <th scope="col" class="px-4 py-3">{m.annotation_sets_list_column_name()}</th>
            <th scope="col" class="px-4 py-3">{m.annotation_sets_list_column_status()}</th>
            <th scope="col" class="px-4 py-3">{m.annotation_sets_list_column_segments()}</th>
            <th scope="col" class="px-4 py-3">{m.annotation_sets_list_column_progress()}</th>
            <th scope="col" class="px-4 py-3">{m.annotation_sets_list_column_created()}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-stone-200 dark:divide-stone-700">
          {#each $setsQuery.data.items as set (set.id)}
            {@const progress = progressPercent(set)}
            <tr class="group cursor-pointer transition-colors hover:bg-stone-50 dark:hover:bg-stone-800/40">
              <td class="px-4 py-3 align-top">
                <a
                  href={detailHref(set.id)}
                  class="block text-sm font-medium text-stone-900 group-hover:text-primary-600 dark:text-stone-100"
                >
                  {set.name}
                </a>
                <div class="mt-0.5 text-xs text-stone-400">{set.segment_length_sec}s</div>
              </td>
              <td class="px-4 py-3 align-top">
                <a href={detailHref(set.id)} class="inline-flex">
                  <span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {statusClass(set.status)}">
                    {statusLabel(set.status)}
                  </span>
                </a>
              </td>
              <td class="px-4 py-3 align-top">
                <a href={detailHref(set.id)} class="block text-sm text-stone-700 dark:text-stone-300">
                  {set.num_segments}
                </a>
              </td>
              <td class="px-4 py-3 align-top">
                <a
                  href={detailHref(set.id)}
                  class="block"
                  aria-label={m.annotation_sets_progress_percent({ percent: String(progress) })}
                >
                  <div class="h-2 w-32 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-700">
                    <div
                      class="h-full rounded-full bg-primary-500 transition-all"
                      style:width="{progress}%"
                    ></div>
                  </div>
                  {#if set.progress}
                    <div class="mt-1 text-xs text-stone-400">
                      {set.progress.annotated}/{set.progress.total}
                    </div>
                  {/if}
                </a>
              </td>
              <td class="px-4 py-3 align-top text-sm text-stone-500">
                <a href={detailHref(set.id)} class="block">
                  {formatDate(set.created_at)}
                </a>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
