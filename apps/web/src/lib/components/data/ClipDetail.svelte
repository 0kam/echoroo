<script lang="ts">
  import type { ClipDetail } from '$lib/types/data';
  import { getClipSpectrogramUrl, getClipAudioUrl, getClipDownloadUrl, updateClip } from '$lib/api/clips';
  import NoteEditor from '$lib/components/data/NoteEditor.svelte';
  import { createMutation, useQueryClient } from '@tanstack/svelte-query';

  export let projectId: string;
  export let recordingId: string;
  export let clip: ClipDetail;

  const queryClient = useQueryClient();

  let audioElement: HTMLAudioElement;
  let isPlaying = false;

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
    isPlaying = !isPlaying;
  }

  function handleAudioEnded() {
    isPlaying = false;
  }

  function handleAudioPause() {
    isPlaying = false;
  }

  function handleAudioPlay() {
    isPlaying = true;
  }

  function handleNoteSave(event: CustomEvent<string>) {
    $noteMutation.mutate(event.detail);
  }
</script>

<div class="clip-detail">
  <!-- Spectrogram -->
  <div class="spectrogram-container">
    <img
      src={getClipSpectrogramUrl(projectId, recordingId, clip.id, { width: 600, height: 200 })}
      alt="Clip spectrogram"
      class="spectrogram"
    />
  </div>

  <!-- Controls -->
  <div class="controls">
    <div class="time-info">
      <span class="label">Time range:</span>
      <span class="time-value">{formatTime(clip.start_time)} - {formatTime(clip.end_time)}</span>
      <span class="duration">({clip.duration.toFixed(2)}s)</span>
    </div>

    <div class="actions">
      <button on:click={togglePlay} class="btn-play">
        {#if isPlaying}
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <rect x="6" y="4" width="4" height="16" fill="currentColor" />
            <rect x="14" y="4" width="4" height="16" fill="currentColor" />
          </svg>
          Pause
        {:else}
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <polygon points="5 3 19 12 5 21 5 3" fill="currentColor" />
          </svg>
          Play
        {/if}
      </button>

      <a href={getClipDownloadUrl(projectId, recordingId, clip.id)} download class="btn-download">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke-width="2" />
          <polyline points="7 10 12 15 17 10" stroke-width="2" />
          <line x1="12" y1="15" x2="12" y2="3" stroke-width="2" />
        </svg>
        Download
      </a>
    </div>
  </div>

  <!-- Notes -->
  <div class="note-section">
    <NoteEditor
      value={clip.note ?? ''}
      placeholder="Add a note about this clip..."
      disabled={$noteMutation.isPending}
      on:save={handleNoteSave}
    />
    {#if $noteMutation.isError}
      <p class="error-text">Failed to save note: {$noteMutation.error?.message}</p>
    {/if}
  </div>

  <!-- Audio element (hidden) -->
  <audio
    bind:this={audioElement}
    src={getClipAudioUrl(projectId, recordingId, clip.id)}
    on:ended={handleAudioEnded}
    on:pause={handleAudioPause}
    on:play={handleAudioPlay}
    preload="none"
    style="display: none;"
  ></audio>
</div>

<style>
  .clip-detail {
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    overflow: hidden;
    background: white;
  }

  .spectrogram-container {
    width: 100%;
    background: #1f2937;
  }

  .spectrogram {
    width: 100%;
    height: auto;
    display: block;
  }

  .controls {
    padding: 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .time-info {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
  }

  .label {
    color: #6b7280;
    font-weight: 500;
  }

  .time-value {
    font-family: monospace;
    color: #111827;
    font-weight: 600;
  }

  .duration {
    color: #6b7280;
    font-size: 0.813rem;
  }

  .actions {
    display: flex;
    gap: 0.75rem;
  }

  .btn-play,
  .btn-download {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
    text-decoration: none;
  }

  .btn-play {
    background: #3b82f6;
    color: white;
    border: 1px solid #3b82f6;
  }

  .btn-play:hover {
    background: #2563eb;
    border-color: #2563eb;
  }

  .btn-download {
    background: #f3f4f6;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .btn-download:hover {
    background: #e5e7eb;
    border-color: #9ca3af;
  }

  .icon {
    width: 16px;
    height: 16px;
  }

  .note-section {
    padding: 1rem;
    background: #f9fafb;
    border-top: 1px solid #e5e7eb;
  }

  .error-text {
    margin: 0.5rem 0 0;
    font-size: 0.813rem;
    color: #dc2626;
  }
</style>
