<script lang="ts">
  import * as m from '$lib/paraglide/messages';
  import { DEFAULT_CONCURRENCY } from '$lib/upload/scheduler';
  import type { FileUiState, PlannedFile } from '$lib/upload/scheduler';

  interface Props {
    files: PlannedFile[];
    fileStates: Record<string, FileUiState>;
    overallPercent: number;
    paused?: boolean;
  }

  let { files, fileStates, overallPercent, paused = false }: Props = $props();

  function percentFor(state: FileUiState | undefined, file: PlannedFile): number {
    if (!state || state.total === 0) return file.declaredSize === 0 ? 100 : 0;
    return Math.max(0, Math.min(100, Math.round((state.sent / state.total) * 100)));
  }

  function sentCount(): number {
    return files.filter((file) => fileStates[file.fileId]?.state === 'done').length;
  }
</script>

<div class="space-y-4">
  <div>
    <div class="mb-1.5 flex justify-between text-sm text-stone-600">
      <span class="font-medium">{m.file_upload_sending_title({ sent: sentCount(), total: files.length })}</span>
      <span>{overallPercent}%</span>
    </div>
    <div class="h-2 overflow-hidden rounded-full bg-stone-200">
      <div
        class="h-full {paused ? 'bg-warning' : 'bg-primary-600'} transition-all duration-300"
        style="width: {overallPercent}%"
      ></div>
    </div>
    <p class="mt-1 text-xs text-stone-400">
      {m.file_upload_sending_hint({ concurrency: DEFAULT_CONCURRENCY })}
    </p>
  </div>

  <ul class="max-h-64 divide-y divide-stone-100 overflow-y-auto rounded-md border border-stone-200">
    {#each files as plannedFile (plannedFile.fileId)}
      {@const state = fileStates[plannedFile.fileId]}
      {@const percent = percentFor(state, plannedFile)}
      <li class="px-3 py-2">
        <div class="mb-1 flex items-center gap-2">
          {#if state?.state === 'done'}
            <svg class="h-3.5 w-3.5 flex-shrink-0 text-success" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
            </svg>
          {:else if state?.state === 'sending'}
            <svg class="h-3.5 w-3.5 flex-shrink-0 animate-spin text-primary-500" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
          {:else if state?.state === 'retrying'}
            <svg class="h-3.5 w-3.5 flex-shrink-0 text-warning" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 11a8.1 8.1 0 00-15.5-2M4 5v4h4M4 13a8.1 8.1 0 0015.5 2M20 19v-4h-4" />
            </svg>
          {:else if state?.state === 'paused'}
            <svg class="h-3.5 w-3.5 flex-shrink-0 text-warning" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5v14M16 5v14" />
            </svg>
          {:else if state?.state === 'failed'}
            <svg class="h-3.5 w-3.5 flex-shrink-0 text-danger" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 6l12 12M18 6L6 18" />
            </svg>
          {:else}
            <div class="h-3.5 w-3.5 flex-shrink-0 rounded-full border-2 border-stone-200" aria-hidden="true"></div>
          {/if}
          <span class="min-w-0 flex-1 truncate text-xs text-stone-700">{plannedFile.file.name}</span>
          <span class="flex-shrink-0 text-xs text-stone-400">
            {#if state?.state === 'retrying' && state.attempt !== undefined && state.maxAttempts !== undefined}
              {m.file_upload_state_retrying({ attempt: state.attempt, max: state.maxAttempts })}
            {:else if state?.state === 'failed'}
              {m.file_upload_state_failed()}
            {:else if state?.state === 'done'}
              {m.file_upload_state_done()}
            {:else if state?.state === 'paused'}
              {m.file_upload_state_stopped({ percent })}
            {:else if state?.state === 'queued'}
              {m.file_upload_state_queued()}
            {:else}
              {m.file_upload_state_sending({ percent })}
            {/if}
          </span>
        </div>
        {#if state?.state === 'failed' && state.message}
          <p class="mb-1 text-xs text-danger">{state.message}</p>
        {/if}
        <div class="h-1 overflow-hidden rounded-full bg-stone-100">
          <div
            class="h-full transition-all duration-200 {state?.state === 'done' ? 'bg-success' : state?.state === 'failed' ? 'bg-danger' : 'bg-primary-500'}"
            style="width: {percent}%"
          ></div>
        </div>
      </li>
    {/each}
  </ul>
</div>
