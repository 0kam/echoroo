<script lang="ts">
  import type { Clip, ClipDetail } from '$lib/types/data';
  import {
    getAuthenticatedClipPlaybackUrl,
    getAuthenticatedClipSpectrogramUrl,
    getAuthenticatedClipDownloadUrl,
    updateClip,
  } from '$lib/api/clips';
  import NoteEditor from '$lib/components/data/NoteEditor.svelte';
  import { createMutation, useQueryClient } from '@tanstack/svelte-query';

  interface Props {
    projectId: string;
    recordingId: string;
    clip: Clip | ClipDetail;
  }

  let { projectId, recordingId, clip = $bindable() }: Props = $props();

  const queryClient = useQueryClient();

  let audioElement = $state<HTMLAudioElement | undefined>(undefined);
  let isPlaying = $state(false);
  let spectrogramUrl = $state<string | null>(null);
  let audioUrl = $state<string | null>(null);
  let mediaLoadError = $state<string | null>(null);
  let mediaRequestId = 0;
  const clipDuration = $derived(
    'duration' in clip ? clip.duration : clip.end_time - clip.start_time
  );

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

  let isDownloading = $state(false);

  async function handleDownload(event: MouseEvent) {
    // Native anchors cannot send Authorization; issue a clip-scoped download
    // media token and navigate to the tokenized BFF download URL instead.
    event.preventDefault();
    if (isDownloading) return;
    isDownloading = true;
    try {
      const url = await getAuthenticatedClipDownloadUrl(projectId, recordingId, clip.id);
      window.location.assign(url);
    } finally {
      isDownloading = false;
    }
  }

  $effect(() => {
    const currentProjectId = projectId;
    const currentRecordingId = recordingId;
    const currentClip = clip;

    mediaRequestId += 1;
    const requestId = mediaRequestId;
    spectrogramUrl = null;
    audioUrl = null;
    mediaLoadError = null;

    void (async () => {
      try {
        const [nextSpectrogramUrl, nextAudioUrl] = await Promise.all([
          getAuthenticatedClipSpectrogramUrl(currentProjectId, currentRecordingId, currentClip, {
            width: 600,
            height: 200,
          }),
          getAuthenticatedClipPlaybackUrl(currentProjectId, currentRecordingId, currentClip),
        ]);

        if (requestId !== mediaRequestId) return;
        spectrogramUrl = nextSpectrogramUrl;
        audioUrl = nextAudioUrl;
      } catch {
        if (requestId !== mediaRequestId) return;
        mediaLoadError = 'Failed to load clip media.';
      }
    })();
  });
</script>

<div class="overflow-hidden rounded-lg border border-card bg-surface-card">
  <!-- Spectrogram -->
  <div class="w-full bg-stone-900">
    {#if spectrogramUrl}
      <img
        src={spectrogramUrl}
        alt="Clip spectrogram"
        data-testid="clip-detail-spectrogram"
        class="block h-auto w-full"
      />
    {:else}
      <div class="flex h-48 items-center justify-center text-sm text-stone-400">
        {mediaLoadError ?? 'Loading clip spectrogram...'}
      </div>
    {/if}
  </div>

  <!-- Controls -->
  <div class="flex flex-wrap items-center justify-between gap-4 p-4">
    <div class="flex items-center gap-2 text-sm">
      <span class="font-medium text-stone-500">Time range:</span>
      <span class="font-mono font-semibold text-stone-900">{formatTime(clip.start_time)} - {formatTime(clip.end_time)}</span>
      <span class="text-xs text-stone-500">({clipDuration.toFixed(2)}s)</span>
    </div>

    <div class="flex gap-3">
      <button
        onclick={togglePlay}
        disabled={!audioUrl}
        data-testid="clip-detail-play"
        class="flex items-center gap-2 rounded-md border border-primary-600 bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400 dark:border-primary-500"
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
        href="#download"
        download
        onclick={handleDownload}
        aria-disabled={isDownloading}
        class="flex items-center gap-2 rounded-md border border-stone-300 bg-stone-100 px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-200 no-underline aria-disabled:opacity-60 aria-disabled:pointer-events-none"
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
      <p class="mt-2 text-xs text-danger">Failed to save note: {$noteMutation.error?.message}</p>
    {/if}
  </div>

  <!-- Audio element (hidden) -->
  <audio
    bind:this={audioElement}
    src={audioUrl ?? undefined}
    data-testid="clip-detail-audio"
    onended={() => { isPlaying = false; }}
    onpause={() => { isPlaying = false; }}
    onplay={() => { isPlaying = true; }}
    preload="none"
    class="hidden"
  ></audio>
</div>
