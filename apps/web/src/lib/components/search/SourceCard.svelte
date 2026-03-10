<script lang="ts">
  /**
   * SourceCard - Compact horizontal card for a single reference sound in the source list.
   *
   * Displays file name/label, clip range, duration, origin badge, and a play/stop button.
   * Audio playback uses the Web Audio API to play the selected clip range.
   */

  import { onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages.js';
  import type { SoundSource } from '$lib/types/search';

  interface Props {
    source: SoundSource;
    onRemove: () => void;
  }

  let { source, onRemove }: Props = $props();

  // Playback state
  let isPlaying = $state(false);
  let audioCtx: AudioContext | null = null;
  let sourceNode: AudioBufferSourceNode | null = null;
  let decodedBuffer: AudioBuffer | null = null;
  let animHandle: number | null = null;

  async function ensureDecoded(): Promise<AudioBuffer | null> {
    if (decodedBuffer) return decodedBuffer;
    if (!source.file && !source.audio_data) return null;

    try {
      const sampleRate = source.sample_rate ?? 48000;
      if (!audioCtx || audioCtx.state === 'closed') {
        audioCtx = new AudioContext({ sampleRate });
      }
      const arrayBuffer = source.file
        ? await source.file.arrayBuffer()
        : source.audio_data!;
      decodedBuffer = await audioCtx.decodeAudioData(arrayBuffer.slice(0));
      return decodedBuffer;
    } catch {
      return null;
    }
  }

  async function togglePlay() {
    if (isPlaying) {
      stopPlayback();
      return;
    }

    const buffer = await ensureDecoded();
    if (!buffer) return;

    if (!audioCtx || audioCtx.state === 'closed') {
      audioCtx = new AudioContext({ sampleRate: source.sample_rate ?? 48000 });
    }

    sourceNode = audioCtx.createBufferSource();
    sourceNode.buffer = buffer;
    sourceNode.connect(audioCtx.destination);

    const startSec = source.start_time ?? 0;
    const endSec = source.end_time ?? (source.duration ?? buffer.duration);
    const clipDuration = endSec - startSec;

    sourceNode.start(0, startSec, clipDuration);
    isPlaying = true;

    const startedAt = audioCtx.currentTime;

    function checkDone() {
      if (!isPlaying) return;
      const elapsed = (audioCtx?.currentTime ?? 0) - startedAt;
      if (elapsed >= clipDuration) {
        stopPlayback();
        return;
      }
      animHandle = requestAnimationFrame(checkDone);
    }
    animHandle = requestAnimationFrame(checkDone);

    sourceNode.onended = () => stopPlayback();
  }

  function stopPlayback() {
    if (animHandle !== null) {
      cancelAnimationFrame(animHandle);
      animHandle = null;
    }
    try {
      sourceNode?.stop();
    } catch {
      // Already stopped
    }
    sourceNode = null;
    isPlaying = false;
  }

  // Derived display values
  let displayName = $derived(
    source.label || source.file?.name || source.xc_id || 'Reference'
  );

  let clipInfo = $derived(() => {
    if (source.start_time != null && source.end_time != null) {
      const dur = source.end_time - source.start_time;
      return `${source.start_time.toFixed(1)}s–${source.end_time.toFixed(1)}s (${dur.toFixed(1)}s)`;
    } else if (source.duration != null) {
      return `${source.duration.toFixed(1)}s (${m.search_source_full()})`;
    }
    return '';
  });

  onDestroy(() => {
    stopPlayback();
    if (audioCtx) {
      audioCtx.close().catch(() => {});
      audioCtx = null;
    }
  });
</script>

<div class="flex items-center gap-3 rounded-lg bg-stone-50 px-3 py-2 dark:bg-stone-800/50">
  <!-- Play / Stop button -->
  <button
    type="button"
    class="shrink-0 text-stone-500 transition-colors hover:text-primary-600"
    onclick={togglePlay}
    aria-label={isPlaying ? m.search_clip_stop() : m.search_clip_play_selection()}
  >
    {#if isPlaying}
      <!-- Stop icon -->
      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <rect x="6" y="6" width="12" height="12" rx="1" />
      </svg>
    {:else}
      <!-- Play icon -->
      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86A1 1 0 0 0 8 5.14z" />
      </svg>
    {/if}
  </button>

  <!-- Info -->
  <div class="min-w-0 flex-1">
    <p class="truncate text-sm text-stone-900 dark:text-stone-100">{displayName}</p>
    <p class="text-xs text-stone-400">{clipInfo()}</p>
  </div>

  <!-- Origin badge -->
  <span class="shrink-0 rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-600 dark:bg-stone-700 dark:text-stone-300">
    {m.search_origin_upload()}
  </span>

  <!-- Remove button -->
  <button
    type="button"
    class="shrink-0 text-stone-300 transition-colors hover:text-stone-500"
    onclick={onRemove}
    aria-label="Remove source"
  >
    <!-- X icon -->
    <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  </button>
</div>
