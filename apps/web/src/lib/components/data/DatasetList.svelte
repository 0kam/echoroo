<script lang="ts">
  import type { Dataset, DatasetStatus, DatasetVisibility } from '$lib/types/data';

  interface Props {
    datasets: Dataset[];
    selectedId?: string | null;
    search?: string;
    statusFilter?: DatasetStatus | '';
    visibilityFilter?: DatasetVisibility | '';
    onSelect?: (dataset: Dataset) => void;
    onDelete?: (dataset: Dataset) => void;
    onFilterChange?: () => void;
  }

  let {
    datasets,
    selectedId = null,
    search = $bindable<string>(''),
    statusFilter = $bindable<DatasetStatus | ''>(''),
    visibilityFilter = $bindable<DatasetVisibility | ''>(''),
    onSelect = () => {},
    onDelete = () => {},
    onFilterChange = () => {},
  }: Props = $props();

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString();
  }

  function getStatusClasses(status: DatasetStatus): string {
    switch (status) {
      case 'pending':
        return 'bg-yellow-100 text-yellow-800';
      case 'scanning':
      case 'processing':
        return 'bg-blue-100 text-blue-800';
      case 'completed':
        return 'bg-green-100 text-green-800';
      case 'failed':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  }

  function getStatusLabel(status: DatasetStatus): string {
    switch (status) {
      case 'pending': return 'Pending';
      case 'scanning': return 'Scanning';
      case 'processing': return 'Processing';
      case 'completed': return 'Ready';
      case 'failed': return 'Failed';
      default: return status;
    }
  }
</script>

<div class="w-full">
  <!-- Filters -->
  <div class="mb-4 flex flex-wrap gap-3">
    <input
      type="text"
      placeholder="Search datasets..."
      bind:value={search}
      oninput={onFilterChange}
      class="min-w-[200px] flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
    />

    <select
      bind:value={statusFilter}
      onchange={onFilterChange}
      class="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
    >
      <option value="">All Statuses</option>
      <option value="pending">Pending</option>
      <option value="scanning">Scanning</option>
      <option value="processing">Processing</option>
      <option value="completed">Ready</option>
      <option value="failed">Failed</option>
    </select>

    <select
      bind:value={visibilityFilter}
      onchange={onFilterChange}
      class="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
    >
      <option value="">All Visibility</option>
      <option value="private">Private</option>
      <option value="public">Public</option>
    </select>
  </div>

  <!-- Dataset list -->
  {#if datasets.length === 0}
    <div class="rounded-lg bg-gray-50 py-12 text-center">
      <svg class="mx-auto mb-3 h-10 w-10 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
      </svg>
      <p class="text-sm text-gray-500">No datasets found. Create your first dataset to get started.</p>
    </div>
  {:else}
    <ul class="flex flex-col gap-2 p-0 list-none">
      {#each datasets as dataset (dataset.id)}
        <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
        <li
          class="flex cursor-pointer items-start justify-between gap-4 rounded-lg border bg-white p-4 transition-all hover:bg-gray-50
            {dataset.id === selectedId ? 'border-blue-500 bg-blue-50' : 'border-gray-200'}"
          role="button"
          tabindex="0"
          onclick={() => onSelect(dataset)}
          onkeydown={(e) => e.key === 'Enter' && onSelect(dataset)}
        >
          <div class="min-w-0 flex-1">
            <div class="mb-2 flex items-center gap-2">
              <h3 class="m-0 text-base font-semibold text-gray-900">{dataset.name}</h3>
              <span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium {getStatusClasses(dataset.status)}">
                {getStatusLabel(dataset.status)}
              </span>
              <span class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium {dataset.visibility === 'public' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}">
                {dataset.visibility}
              </span>
            </div>

            {#if dataset.description}
              <p class="mb-2 text-sm text-gray-500">{dataset.description}</p>
            {/if}

            <div class="mb-1 flex flex-wrap gap-4">
              <span class="text-xs text-gray-500">
                <span class="font-medium">Path:</span>
                <code class="ml-1 rounded bg-gray-100 px-1 py-0.5 font-mono text-xs">{dataset.audio_dir}</code>
              </span>
              <span class="text-xs text-gray-500">
                <span class="font-medium">Files:</span> {dataset.processed_files} / {dataset.total_files}
              </span>
            </div>

            <p class="m-0 text-xs text-gray-400">Created: {formatDate(dataset.created_at)}</p>
          </div>

          <div class="ml-2 flex-shrink-0">
            <button
              class="rounded border border-red-200 bg-white px-2 py-1 text-xs font-medium text-red-600 transition-colors hover:border-red-300 hover:bg-red-50"
              onclick={(e) => { e.stopPropagation(); onDelete(dataset); }}
              aria-label="Delete dataset"
            >
              Delete
            </button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>
