<script lang="ts">
  /**
   * Project detail layout with sidebar navigation
   */

  import { page } from '$app/stores';

  $: projectId = $page.params.id;

  // Navigation items for the project sidebar
  const navItems = [
    {
      name: 'Overview',
      hrefSuffix: '',
      icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6',
    },
    {
      name: 'Datasets',
      hrefSuffix: '/datasets',
      icon: 'M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4',
    },
    {
      name: 'Recordings',
      hrefSuffix: '/recordings',
      icon: 'M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z',
    },
    {
      name: 'Sites',
      hrefSuffix: '/sites',
      icon: 'M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z M15 11a3 3 0 11-6 0 3 3 0 016 0z',
    },
    {
      name: 'Annotations',
      hrefSuffix: '/annotations',
      icon: 'M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z',
    },
    {
      name: 'Members',
      hrefSuffix: '/members',
      icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z',
    },
    {
      name: 'Settings',
      hrefSuffix: '/settings',
      icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z',
    },
  ];

  /**
   * Check if a nav item is active based on the current pathname.
   * The Overview item is only active on an exact match.
   */
  function isActive(hrefSuffix: string): boolean {
    const href = `/projects/${projectId}${hrefSuffix}`;
    if (hrefSuffix === '') {
      return $page.url.pathname === href;
    }
    return $page.url.pathname.startsWith(href);
  }
</script>

<div class="flex h-screen bg-gray-50">
  <!-- Sidebar -->
  <aside class="w-56 flex-shrink-0 border-r border-gray-200 bg-white">
    <!-- Back link -->
    <div class="flex h-14 items-center border-b border-gray-200 px-4">
      <a
        href="/projects"
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
        All Projects
      </a>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 space-y-0.5 p-3">
      {#each navItems as item}
        <a
          href="/projects/{projectId}{item.hrefSuffix}"
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
    <slot />
  </main>
</div>
