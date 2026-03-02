<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { fetchDirectories } from '$lib/api/datasets';

  interface Props {
    onSelect: (path: string) => void;
    selectedPath?: string;
  }

  let { onSelect, selectedPath = '' }: Props = $props();

  let currentPath = $state('');
  let pathHistory = $state<string[]>([]);

  const directoriesQuery = $derived(
    createQuery({
      queryKey: ['directories', currentPath],
      queryFn: () => fetchDirectories(currentPath || undefined),
    })
  );

  function navigateTo(path: string) {
    if (currentPath) {
      pathHistory = [...pathHistory, currentPath];
    }
    currentPath = path;
  }

  function goBack() {
    if (pathHistory.length > 0) {
      const lastPath = pathHistory[pathHistory.length - 1];
      currentPath = lastPath ?? '';
      pathHistory = pathHistory.slice(0, -1);
    } else {
      currentPath = '';
    }
  }

  function goToRoot() {
    pathHistory = [];
    currentPath = '';
  }

  function selectDirectory(path: string) {
    onSelect(path);
  }

  const breadcrumbs = $derived(currentPath ? currentPath.split('/').filter((p) => p) : []);

  function navigateToBreadcrumb(index: number) {
    const parts = currentPath.split('/').filter((p) => p);
    const newPath = '/' + parts.slice(0, index + 1).join('/');
    currentPath = newPath;
    pathHistory = [];
  }
</script>

<div class="overflow-hidden rounded-lg border border-gray-200">
  <!-- Breadcrumb navigation -->
  <div class="flex items-center overflow-x-auto whitespace-nowrap border-b border-gray-200 bg-gray-50 px-3 py-2">
    <button
      onclick={goToRoot}
      class="flex items-center gap-1 rounded px-2 py-1 text-sm text-blue-600 hover:underline"
    >
      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
      </svg>
      Root
    </button>
    {#each breadcrumbs as crumb, index}
      <span class="mx-1 text-gray-400">/</span>
      <button
        onclick={() => navigateToBreadcrumb(index)}
        class="rounded px-2 py-1 text-sm text-blue-600 hover:underline"
      >
        {crumb}
      </button>
    {/each}
  </div>

  <!-- Navigation controls -->
  <div class="flex items-center justify-between border-b border-gray-200 bg-white px-3 py-2">
    <button
      onclick={goBack}
      disabled={pathHistory.length === 0}
      class="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
    >
      Back
    </button>
    <div class="text-sm text-gray-500">
      Current path:
      <code class="ml-1 rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs">{$directoriesQuery.data?.path || '/'}</code>
    </div>
  </div>

  <!-- Directory list -->
  <div class="max-h-96 overflow-y-auto">
    {#if $directoriesQuery.isLoading}
      <div class="flex items-center justify-center py-8 text-sm text-gray-500">
        <svg class="mr-2 h-4 w-4 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        Loading directories...
      </div>
    {:else if $directoriesQuery.isError}
      <div class="py-6 text-center text-sm text-red-600">
        Error: {$directoriesQuery.error?.message}
      </div>
    {:else if $directoriesQuery.data}
      {#if $directoriesQuery.data.directories.length === 0}
        <div class="py-8 text-center text-sm text-gray-400">No subdirectories found</div>
      {:else}
        <ul class="m-0 list-none p-0">
          {#each $directoriesQuery.data.directories as dir}
            <li
              class="flex items-center justify-between border-b border-gray-100 px-3 py-2.5 transition-colors last:border-b-0 hover:bg-gray-50
                {selectedPath === dir.path ? 'bg-blue-50' : ''}"
            >
              <button
                onclick={() => navigateTo(dir.path)}
                class="flex items-center gap-2 border-0 bg-transparent p-0 text-left"
              >
                <svg class="h-5 w-5 flex-shrink-0 text-yellow-500" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z" />
                </svg>
                <span class="text-sm font-medium text-gray-800 hover:text-blue-600">{dir.name}</span>
              </button>

              <div class="ml-3 flex items-center gap-2">
                {#if dir.audio_file_count > 0}
                  <span class="text-xs text-gray-400">
                    {dir.audio_file_count} file{dir.audio_file_count !== 1 ? 's' : ''}
                    {#if dir.formats.length > 0}
                      ({dir.formats.join(', ')})
                    {/if}
                  </span>
                {/if}
                <button
                  onclick={() => selectDirectory(dir.path)}
                  class="rounded bg-blue-600 px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-blue-700"
                >
                  Select
                </button>
              </div>
            </li>
          {/each}
        </ul>
      {/if}
    {/if}
  </div>

  <!-- Selected path display -->
  {#if selectedPath}
    <div class="border-t border-green-200 bg-green-50 px-3 py-2 text-sm">
      <span class="font-medium text-green-800">Selected:</span>
      <code class="ml-2 rounded bg-white px-1.5 py-0.5 font-mono text-xs text-green-800">{selectedPath}</code>
    </div>
  {/if}
</div>
