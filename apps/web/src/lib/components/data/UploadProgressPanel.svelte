<script lang="ts">
  /**
   * UploadProgressPanel - Displays per-file upload progress during the uploading step.
   *
   * Shows an overall progress bar and a scrollable per-file progress list.
   */

  const UPLOAD_CONCURRENCY = 3;

  interface Props {
    files: File[];
    fileUploadProgress: Record<number, number>;
    overallPercent: number;
  }

  let { files, fileUploadProgress, overallPercent }: Props = $props();
</script>

<div class="space-y-4">
  <!-- Overall progress bar -->
  <div>
    <div class="mb-1.5 flex justify-between text-sm text-stone-600">
      <span class="font-medium">Uploading files</span>
      <span>{overallPercent}%</span>
    </div>
    <div class="h-2 overflow-hidden rounded-full bg-stone-200">
      <div
        class="h-full bg-primary-600 transition-all duration-300"
        style="width: {overallPercent}%"
      ></div>
    </div>
    <p class="mt-1 text-xs text-stone-400">
      Uploading {files.length} file{files.length !== 1 ? 's' : ''}
      &mdash; up to {UPLOAD_CONCURRENCY} at a time
    </p>
  </div>

  <!-- Per-file progress list -->
  <ul class="max-h-64 divide-y divide-stone-100 overflow-y-auto rounded-md border border-stone-200">
    {#each files as file, i}
      {@const pct = fileUploadProgress[i] ?? 0}
      <li class="px-3 py-2">
        <div class="mb-1 flex items-center gap-2">
          {#if pct >= 100}
            <svg
              class="h-3.5 w-3.5 flex-shrink-0 text-success"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
            </svg>
          {:else if pct > 0}
            <svg
              class="h-3.5 w-3.5 flex-shrink-0 animate-spin text-primary-500"
              fill="none"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
          {:else}
            <div class="h-3.5 w-3.5 flex-shrink-0 rounded-full border-2 border-stone-200" aria-hidden="true"></div>
          {/if}
          <span class="min-w-0 flex-1 truncate text-xs text-stone-700">{file.name}</span>
          <span class="flex-shrink-0 text-xs text-stone-400">{pct}%</span>
        </div>
        <div class="h-1 overflow-hidden rounded-full bg-stone-100">
          <div
            class="h-full transition-all duration-200 {pct >= 100 ? 'bg-success' : 'bg-primary-500'}"
            style="width: {pct}%"
          ></div>
        </div>
      </li>
    {/each}
  </ul>
</div>
