<script lang="ts">
  import type { Site } from '$lib/types/data';

  interface Props {
    sites: Site[];
    selectedId?: string | null;
    onSelect?: (site: Site) => void;
    onDelete?: (site: Site) => void;
  }

  let {
    sites,
    selectedId = null,
    onSelect = () => {},
    onDelete = () => {},
  }: Props = $props();

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString();
  }
</script>

<div class="w-full">
  {#if sites.length === 0}
    <div class="rounded-lg bg-gray-50 py-12 text-center">
      <svg class="mx-auto mb-3 h-10 w-10 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
      <p class="text-sm text-gray-500">No sites found. Create your first site to get started.</p>
    </div>
  {:else}
    <ul class="flex flex-col gap-2 p-0 list-none">
      {#each sites as site (site.id)}
        <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
        <li
          class="flex cursor-pointer items-center justify-between rounded-lg border bg-white p-4 transition-all hover:bg-gray-50
            {site.id === selectedId ? 'border-blue-500 bg-blue-50' : 'border-gray-200'}"
          role="button"
          tabindex="0"
          onclick={() => onSelect(site)}
          onkeydown={(e) => e.key === 'Enter' && onSelect(site)}
        >
          <div class="min-w-0 flex-1">
            <h3 class="m-0 mb-1 text-base font-semibold text-gray-900">{site.name}</h3>
            <p class="m-0 mb-1 text-xs text-gray-500">
              H3:
              <code class="rounded bg-gray-100 px-1 py-0.5 font-mono">{site.h3_index}</code>
            </p>
            <p class="m-0 text-xs text-gray-400">Created: {formatDate(site.created_at)}</p>
          </div>
          <div class="ml-4 flex-shrink-0">
            <button
              class="rounded border border-red-200 bg-white px-2 py-1 text-xs font-medium text-red-600 transition-colors hover:border-red-300 hover:bg-red-50"
              onclick={(e) => { e.stopPropagation(); onDelete(site); }}
              aria-label="Delete site"
            >
              Delete
            </button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>
