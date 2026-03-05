<script lang="ts">
  /**
   * Project detail layout with sidebar navigation.
   * Rendered inside the (app) layout which provides the top header.
   */

  import { page } from '$app/stores';
  import { createQuery } from '@tanstack/svelte-query';
  import { projectsApi } from '$lib/api/projects';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    children: import('svelte').Snippet;
  }

  let { children }: Props = $props();

  const projectId = $derived($page.params.id);

  // Fetch project data to display name in the sidebar header
  const projectQuery = $derived(
    createQuery({
      queryKey: ['project', projectId],
      queryFn: () => projectsApi.get(projectId as string),
      enabled: !!projectId,
    })
  );

  // Navigation items for the project sidebar (5 items)
  const navItems = $derived([
    {
      name: m.sidebar_nav_overview(),
      hrefSuffix: '',
      icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6',
    },
    {
      name: m.sidebar_nav_sites_data(),
      hrefSuffix: '/data',
      icon: 'M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4',
    },
    {
      name: m.sidebar_nav_detections(),
      hrefSuffix: '/detections',
      icon: 'M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3',
    },
    {
      name: m.sidebar_nav_reports(),
      hrefSuffix: '/reports',
      icon: 'M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
    },
    {
      name: m.sidebar_nav_settings(),
      hrefSuffix: '/settings',
      icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z',
    },
  ]);

  /**
   * Check if a nav item is active based on the current pathname.
   * The Overview item is only active on an exact match.
   */
  function isActive(hrefSuffix: string): boolean {
    const href = `/projects/${projectId}${hrefSuffix}`;
    if (hrefSuffix === '') {
      return $page.url.pathname === href || $page.url.pathname === `/en${href}` || $page.url.pathname === `/ja${href}`;
    }
    return $page.url.pathname.includes(href);
  }
</script>

<div class="flex flex-1 overflow-hidden bg-gray-50">
  <!-- Sidebar -->
  <aside class="w-56 flex-shrink-0 border-r border-gray-200 bg-white">
    <!-- Back link -->
    <div class="flex h-14 items-center border-b border-gray-200 px-4">
      <a
        href={localizeHref('/projects')}
        class="flex items-center text-sm font-medium text-gray-500 hover:text-gray-900"
      >
        <svg
          class="mr-1.5 h-4 w-4"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M15 19l-7-7 7-7"
          />
        </svg>
        {m.sidebar_all_projects()}
      </a>
    </div>

    <!-- Project name -->
    <div class="border-b border-gray-200 px-4 py-3">
      {#if $projectQuery.isLoading}
        <div class="h-4 w-32 animate-pulse rounded bg-gray-200"></div>
      {:else if $projectQuery.data}
        <p class="truncate text-xs font-semibold text-gray-900" title={$projectQuery.data.name}>
          {$projectQuery.data.name}
        </p>
      {:else}
        <p class="text-xs text-gray-400">{m.sidebar_project_loading()}</p>
      {/if}
    </div>

    <!-- Navigation -->
    <nav class="flex-1 space-y-0.5 p-3">
      {#each navItems as item}
        <a
          href={localizeHref(`/projects/${projectId}${item.hrefSuffix}`)}
          class="flex items-center rounded-lg px-3 py-2 text-sm font-medium transition-colors {isActive(
            item.hrefSuffix
          )
            ? 'bg-blue-50 text-blue-700'
            : 'text-gray-700 hover:bg-gray-50'}"
        >
          <svg class="mr-2.5 h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={item.icon} />
          </svg>
          {item.name}
        </a>
      {/each}
    </nav>
  </aside>

  <!-- Main Content -->
  <main class="flex-1 overflow-auto">
    {@render children()}
  </main>
</div>
