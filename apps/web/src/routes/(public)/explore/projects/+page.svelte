<script lang="ts">
  /**
   * Public projects index — Phase 5 US1 (T210 補足).
   *
   * Lists Public + Active projects visible to Guest callers via
   * `/web-api/v1/projects/` (T201). Each card links to the public detail
   * page at `/explore/projects/{id}`. Pagination is intentionally minimal
   * (page / next / prev) — full faceted search is a later-phase concern.
   */

  import { createQuery } from '@tanstack/svelte-query';
  import { ApiError, apiClient } from '$lib/api/client';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  type ProjectVisibility = 'public' | 'restricted';
  type ProjectStatus = 'active' | 'dormant' | 'archived';
  type ProjectLicense = 'CC0' | 'CC-BY' | 'CC-BY-NC' | 'CC-BY-SA';

  interface PublicOwner {
    id: string;
    display_name: string | null;
  }

  interface PublicProject {
    id: string;
    name: string;
    description: string | null;
    visibility: ProjectVisibility;
    license: ProjectLicense;
    status: ProjectStatus;
    owner: PublicOwner;
    created_at: string;
  }

  interface PublicProjectListResponse {
    items: PublicProject[];
    total: number;
    page: number;
    limit: number;
  }

  let page = $state(1);
  const pageSize = 20;

  const locale = $derived(getLocale());

  const listQuery = $derived(
    createQuery<PublicProjectListResponse, ApiError>({
      queryKey: ['public-projects-list', page, locale],
      queryFn: () =>
        apiClient.get<PublicProjectListResponse>(
          `/web-api/v1/projects/?page=${page}&limit=${pageSize}`
        ),
      retry: false,
    })
  );

  const items = $derived($listQuery.data?.items ?? []);
  const total = $derived($listQuery.data?.total ?? 0);
  const totalPages = $derived(Math.max(1, Math.ceil(total / pageSize)));
  const isLoading = $derived($listQuery.isLoading);
  const queryError = $derived($listQuery.error);

  function previousPage() {
    if (page > 1) page -= 1;
  }
  function nextPage() {
    if (page < totalPages) page += 1;
  }

  function formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleDateString(locale);
    } catch {
      return iso;
    }
  }
</script>

<svelte:head>
  <title>{m.public_projects_index_title()} - Echoroo</title>
</svelte:head>

<div class="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
  <header class="mb-6">
    <h1 class="text-3xl font-bold text-stone-900">{m.public_projects_index_title()}</h1>
    <p class="mt-2 text-sm text-stone-600">{m.public_projects_index_subtitle()}</p>
  </header>

  {#if isLoading}
    <div class="flex items-center justify-center py-12" aria-live="polite">
      <svg
        class="h-8 w-8 animate-spin text-primary-600"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
        ></circle>
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        ></path>
      </svg>
      <span class="sr-only">{m.public_project_detail_loading()}</span>
    </div>
  {:else if queryError}
    <div class="rounded-md bg-danger-light p-4" role="alert">
      <p class="text-sm font-medium text-danger">
        {queryError instanceof ApiError
          ? queryError.detail || queryError.message
          : m.public_projects_index_load_error()}
      </p>
    </div>
  {:else if items.length === 0}
    <div class="rounded-md border-2 border-dashed border-stone-300 p-12 text-center">
      <h2 class="mt-2 text-sm font-medium text-stone-900">
        {m.public_projects_index_empty_title()}
      </h2>
      <p class="mt-1 text-sm text-stone-500">{m.public_projects_index_empty_body()}</p>
    </div>
  {:else}
    <ul class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {#each items as p (p.id)}
        <li>
          <a
            href={localizeHref(`/explore/projects/${p.id}`)}
            class="flex h-full flex-col rounded-lg bg-surface-card p-5 shadow transition hover:shadow-md"
          >
            <div class="mb-2 flex flex-wrap gap-1.5">
              <span
                class="inline-flex items-center rounded-full bg-success-light px-2 py-0.5 text-xs font-medium text-success"
              >
                {m.public_project_detail_visibility_public()}
              </span>
              <span
                class="inline-flex items-center rounded-full bg-stone-100 px-2 py-0.5 text-xs font-medium text-stone-700 dark:bg-stone-700 dark:text-stone-200"
              >
                {p.license}
              </span>
            </div>
            <h2 class="mb-1 text-base font-semibold text-stone-900">{p.name}</h2>
            {#if p.description}
              <p class="line-clamp-3 text-sm text-stone-600">{p.description}</p>
            {:else}
              <p class="text-sm italic text-stone-400">
                {m.public_project_detail_no_description()}
              </p>
            {/if}
            <div class="mt-auto pt-3 text-xs text-stone-500">
              {m.public_project_detail_byline({
                owner: p.owner.display_name ?? m.public_project_detail_owner_anonymous(),
                date: formatDate(p.created_at),
              })}
            </div>
          </a>
        </li>
      {/each}
    </ul>

    {#if totalPages > 1}
      <nav
        class="mt-6 flex items-center justify-between"
        aria-label={m.public_projects_index_pagination_aria()}
      >
        <button
          type="button"
          onclick={previousPage}
          disabled={page <= 1}
          class="rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.public_projects_index_prev()}
        </button>
        <span class="text-sm text-stone-600">
          {m.public_projects_index_page_indicator({ page, total: totalPages })}
        </span>
        <button
          type="button"
          onclick={nextPage}
          disabled={page >= totalPages}
          class="rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.public_projects_index_next()}
        </button>
      </nav>
    {/if}
  {/if}
</div>
