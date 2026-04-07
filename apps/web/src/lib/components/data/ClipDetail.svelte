<script lang="ts">
  import type { ClipDetail } from '$lib/types/data';
  import { getClipSpectrogramUrl, getClipAudioUrl, getClipDownloadUrl, updateClip } from '$lib/api/clips';
  import NoteEditor from '$lib/components/data/NoteEditor.svelte';
  import { createMutation, useQueryClient } from '@tanstack/svelte-query';

  interface Props {
    projectId: string;
    recordingId: string;
    clip: ClipDetail;
  }

  let { projectId, recordingId, clip = $bindable() }: Props = $props();

  const queryClient = useQueryClient();

  let audioElement = $state<HTMLAudioElement | undefined>(undefined);
  let isPlaying = $state(false);

  // Note update mutation
  const noteMutation = createMutation({
    mutationFn: (note: string) =>
      updateClip(projectId, recordingId, clip.id, { note: note || null }),
    onSuccess: (updatedClip) => {
      clip = { ...clip, note: updatedClip.note };
      queryClient.invalidateQueries({ queryKey: ['clips', projectId, recordingId] });
    },
  });

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(2);
    return `${mins}:${secs.padStart(5, '0')}`;
  }

  function togglePlay() {
    if (isPlaying) {
      audioElement?.pause();
    } else {
      audioElement?.play();
    }
  }

  function handleNoteSave(newNote: string) {
    $noteMutation.mutate(newNote);
  }
</script>

<div class="overflow-hidden rounded-lg border border-card bg-surface-card">
  <!-- Spectrogram -->
  <div class="w-full bg-stone-900">
    <img
      src={getClipSpectrogramUrl(projectId, recordingId, clip.id, { width: 600, height: 200 })}
      alt="Clip spectrogram"
      class="block h-auto w-full"
    />
  </div>

  <!-- Controls -->
  <div class="flex flex-wrap items-center justify-between gap-4 p-4">
    <div class="flex items-center gap-2 text-sm">
      <span class="font-medium text-stone-500">Time range:</span>
      <span class="font-mono font-semibold text-stone-900">{formatTime(clip.start_time)} - {formatTime(clip.end_time)}</span>
      <span class="text-xs text-stone-500">({clip.duration.toFixed(2)}s)</span>
    </div>

    <div class="flex gap-3">
      <button
        onclick={togglePlay}
        class="flex items-center gap-2 rounded-md border border-primary-600 bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700"
      >
        {#if isPlaying}
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="4" width="4" height="16" />
            <rect x="14" y="4" width="4" height="16" />
          </svg>
          Pause
        {:else}
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
          Play
        {/if}
      </button>

      <a
        href={getClipDownloadUrl(projectId, recordingId, clip.id)}
        download
        class="flex items-center gap-2 rounded-md border border-stone-300 bg-stone-100 px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-200 no-underline"
      >
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke-width="2" />
          <polyline points="7 10 12 15 17 10" stroke-width="2" />
          <line x1="12" y1="15" x2="12" y2="3" stroke-width="2" />
        </svg>
        Download
      </a>
    </div>
  </div>

  <!-- Notes -->
  <div class="border-t border-stone-200 bg-stone-50 p-4">
    <NoteEditor
      value={clip.note ?? ''}
      placeholder="Add a note about this clip..."
      disabled={$noteMutation.isPending}
      onSave={handleNoteSave}
    />
    {#if $noteMutation.isError}
      <p class="mt-2 text-xs text-red-600">Failed to save note: {$noteMutation.error?.message}</p>
    {/if}
  </div>

  <!-- Audio element (hidden) -->
  <audio
    bind:this={audioElement}
    src={getClipAudioUrl(projectId, recordingId, clip.id)}
    onended={() => { isPlaying = false; }}
    onpause={() => { isPlaying = false; }}
    onplay={() => { isPlaying = true; }}
    preload="none"
    class="hidden"
  ></audio>
</div>
