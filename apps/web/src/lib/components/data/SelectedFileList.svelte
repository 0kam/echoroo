<script lang="ts">
  /**
   * SelectedFileList - Scrollable list of selected audio files with remove buttons.
   *
   * Shows file name and size for each file. Provides clear-all and per-file removal.
   */

  interface Props {
    files: File[];
    totalBytes: number;
    onRemove: (index: number) => void;
    onClearAll: () => void;
    onUpload: () => void;
  }

  let { files, totalBytes, onRemove, onClearAll, onUpload }: Props = $props();

  function formatBytes(bytes: number): string {
    if (bytes === 0) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }
</script>

<div class="mb-4">
  <div class="mb-2 flex items-center justify-between">
    <span class="text-sm font-medium text-stone-700">
      {files.length} file{files.length !== 1 ? 's' : ''} selected
      <span class="font-normal text-stone-400">({formatBytes(totalBytes)})</span>
    </span>
    <button
      onclick={onClearAll}
      class="text-xs text-stone-400 underline hover:text-stone-600"
    >
      Clear all
    </button>
  </div>

  <ul class="max-h-60 divide-y divide-stone-100 overflow-y-auto rounded-md border border-stone-200">
    {#each files as file, i}
      <li class="flex items-center gap-3 px-3 py-2">
        <svg
          class="h-4 w-4 flex-shrink-0 text-stone-400"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          aria-hidden="true"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
          />
        </svg>
        <span class="min-w-0 flex-1 truncate text-sm text-stone-700">{file.name}</span>
        <span class="flex-shrink-0 text-xs text-stone-400">{formatBytes(file.size)}</span>
        <button
          onclick={() => onRemove(i)}
          class="flex-shrink-0 rounded p-0.5 text-stone-300 hover:bg-stone-100 hover:text-stone-500"
          aria-label="Remove {file.name}"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
            <line x1="18" y1="6" x2="6" y2="18" stroke-width="2.5" />
            <line x1="6" y1="6" x2="18" y2="18" stroke-width="2.5" />
          </svg>
        </button>
      </li>
    {/each}
  </ul>
</div>

<div class="flex justify-end">
  <button
    onclick={onUpload}
    class="rounded-md bg-primary-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
  >
    Upload {files.length} File{files.length !== 1 ? 's' : ''}
  </button>
</div>
