<script lang="ts">
  /**
   * SourceCard - Compact horizontal card for a single reference sound in the source list.
   *
   * Displays file name/label, clip range, duration, origin badge, and a play/stop button.
   * Supports an inline SpectrogramClipEditor for non-readonly sources.
   * For readonly sources shows a SpectrogramViewer triggered by clicking the source name.
   *
   * Sub-components:
   * - SourcePlayButton: handles play/stop for upload and streaming (URL/S3) sources
   * - SourceInfo: renders name, clip range, and XC metadata
   */

  import { onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages.js';
  import type { SoundSource } from '$lib/types/search';
  import { fetchXenoCantoAudio } from '$lib/api/search';
  import SpectrogramClipEditor from './SpectrogramClipEditor.svelte';
  import SpectrogramViewer from './SpectrogramViewer.svelte';
  import SourcePlayButton from './SourcePlayButton.svelte';
  import SourceInfo from './SourceInfo.svelte';

  interface Props {
    source: SoundSource;
    /** Project ID required for the Xeno-canto audio proxy endpoint */
    projectId: string;
    /** Model name passed to SpectrogramClipEditor for min-clip enforcement */
    modelName?: string;
    onRemove: () => void;
    /** Called when the user confirms a new clip range in the editor */
    onUpdate?: (updates: { start_time?: number; end_time?: number }) => void;
    /** When true, hides remove and edit-clip controls (used for session-loaded sources) */
    readonly?: boolean;
  }

  let { source, projectId, modelName = 'perch', onRemove, onUpdate, readonly = false }: Props = $props();

  // ── Upload playback (Web Audio API) ───────────────────────────────────────
  let isPlaying = $state(false);
  let audioCtx: AudioContext | null = null;
  let sourceNode: AudioBufferSourceNode | null = null;
  let decodedBuffer: AudioBuffer | null = null;
  let animHandle: number | null = null;

  // ── URL / S3 playback (HTML Audio element) ────────────────────────────────
  let urlAudio = $state<HTMLAudioElement | null>(null);
  let isUrlPlaying = $state(false);
  let urlAudioError = $state(false);

  // ── Clip editor state ─────────────────────────────────────────────────────
  let showEditor = $state(false);
  let isLoadingAudio = $state(false);
  let fetchAudioError = $state<string | null>(null);
  let editorAudioData = $state<ArrayBuffer | null>(null);
  let editorDuration = $state(0);
  let editorSampleRate = $state(48000);

  // ── Readonly spectrogram viewer state ─────────────────────────────────────
  let showSpectrogram = $state(false);
  let spectrogramAudioData = $state<ArrayBuffer | null>(null);
  let spectrogramDuration = $state(0);
  let spectrogramSampleRate = $state(48000);
  let isLoadingSpectrogram = $state(false);
  let spectrogramLoadError = $state<string | null>(null);

  // Local mutable clip times for the editor (before confirm)
  let editorStart = $state(source.start_time ?? 0);
  let editorEnd = $state(source.end_time ?? (source.duration ?? 0));

  // ── Upload playback helpers ───────────────────────────────────────────────

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

  // ── URL / S3 playback helpers ─────────────────────────────────────────────

  function toggleUrlPlay() {
    if (isUrlPlaying) {
      urlAudio?.pause();
      isUrlPlaying = false;
      return;
    }

    urlAudioError = false;

    if (!urlAudio) {
      const url = source.origin === 's3' ? source.streamUrl : source.source_url;
      if (!url) return;
      const audio = new Audio(url);
      audio.onended = () => { isUrlPlaying = false; };
      audio.onerror = () => { urlAudioError = true; isUrlPlaying = false; };
      urlAudio = audio;
    }

    isUrlPlaying = true;
    urlAudio.play().catch(() => {
      urlAudioError = true;
      isUrlPlaying = false;
    });
  }

  function stopPlayback() {
    if (animHandle !== null) {
      cancelAnimationFrame(animHandle);
      animHandle = null;
    }
    try { sourceNode?.stop(); } catch { /* Already stopped */ }
    sourceNode = null;
    isPlaying = false;
  }

  // ── Readonly spectrogram helpers ──────────────────────────────────────────

  async function toggleSpectrogram() {
    if (showSpectrogram) {
      showSpectrogram = false;
      return;
    }

    if (spectrogramAudioData) {
      showSpectrogram = true;
      return;
    }

    spectrogramLoadError = null;
    isLoadingSpectrogram = true;

    try {
      let arrayBuffer: ArrayBuffer;

      if (source.origin === 'upload') {
        if (source.audio_data) {
          arrayBuffer = source.audio_data;
        } else if (source.file) {
          arrayBuffer = await source.file.arrayBuffer();
        } else {
          throw new Error('No audio data available');
        }
      } else if (source.origin === 's3' && source.streamUrl) {
        const response = await fetch(source.streamUrl, { credentials: 'include' });
        if (!response.ok) throw new Error(`Failed to fetch audio: ${response.status}`);
        arrayBuffer = await response.arrayBuffer();
      } else if (source.origin === 'url' && source.xc_id) {
        arrayBuffer = await fetchXenoCantoAudio(projectId, source.xc_id);
      } else {
        throw new Error('No audio source available');
      }

      const ctx = new AudioContext();
      const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0));
      spectrogramDuration = decoded.duration;
      spectrogramSampleRate = decoded.sampleRate;
      await ctx.close();

      spectrogramAudioData = arrayBuffer;
      showSpectrogram = true;
    } catch (err) {
      spectrogramLoadError = err instanceof Error ? err.message : 'Failed to load audio';
    } finally {
      isLoadingSpectrogram = false;
    }
  }

  // ── Clip editor helpers ───────────────────────────────────────────────────

  async function openEditor() {
    fetchAudioError = null;
    isLoadingAudio = true;

    try {
      let arrayBuffer: ArrayBuffer;

      if (source.origin === 'upload') {
        if (source.audio_data) {
          arrayBuffer = source.audio_data;
        } else if (source.file) {
          arrayBuffer = await source.file.arrayBuffer();
        } else {
          throw new Error('No audio data available');
        }
      } else {
        if (!source.xc_id) throw new Error('No Xeno-canto ID available');
        arrayBuffer = await fetchXenoCantoAudio(projectId, source.xc_id);
      }

      const ctx = new AudioContext();
      const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0));
      editorDuration = decoded.duration;
      editorSampleRate = decoded.sampleRate;
      await ctx.close();

      editorAudioData = arrayBuffer;
      editorStart = source.start_time ?? 0;
      editorEnd = source.end_time ?? editorDuration;
    } catch (err) {
      fetchAudioError = err instanceof Error ? err.message : m.search_fetch_audio_error();
      isLoadingAudio = false;
      return;
    }

    isLoadingAudio = false;
    showEditor = true;
  }

  function closeEditor() {
    showEditor = false;
    editorAudioData = null;
    fetchAudioError = null;
  }

  function handleEditorRangeChange(start: number, end: number) {
    editorStart = start;
    editorEnd = end;
  }

  function confirmClip() {
    onUpdate?.({
      start_time: editorStart === 0 ? undefined : editorStart,
      end_time: editorEnd === editorDuration ? undefined : editorEnd,
    });
    closeEditor();
  }

  // ── Derived display values ────────────────────────────────────────────────

  const displayName = $derived(
    source.label || source.file?.name || source.xc_id || 'Reference'
  );

  const clipInfo = $derived(() => {
    if (source.start_time != null && source.end_time != null) {
      const dur = source.end_time - source.start_time;
      return `${source.start_time.toFixed(1)}s–${source.end_time.toFixed(1)}s (${dur.toFixed(1)}s)`;
    } else if (source.duration != null) {
      return `${source.duration.toFixed(1)}s (${m.search_source_full()})`;
    }
    return '';
  });

  const hasClipRange = $derived(source.start_time != null || source.end_time != null);

  // ── Cleanup ───────────────────────────────────────────────────────────────

  onDestroy(() => {
    stopPlayback();
    if (audioCtx) {
      audioCtx.close().catch(() => {});
      audioCtx = null;
    }
    if (urlAudio) {
      urlAudio.pause();
      urlAudio.src = '';
      urlAudio = null;
    }
  });
</script>

<div class="rounded-lg bg-stone-50 dark:bg-stone-800/50">
  <!-- Main card row -->
  <div class="flex items-center gap-3 px-3 py-2">
    <!-- Play / Stop button -->
    <SourcePlayButton
      {source}
      {isPlaying}
      {isUrlPlaying}
      {urlAudioError}
      onTogglePlay={togglePlay}
      onToggleUrlPlay={toggleUrlPlay}
    />

    <!-- Source info (name, clip range, metadata) -->
    <SourceInfo
      {source}
      {displayName}
      clipInfo={clipInfo()}
      {hasClipRange}
      {readonly}
      {showSpectrogram}
      {isLoadingSpectrogram}
      onToggleSpectrogram={toggleSpectrogram}
    />

    <!-- Origin badge -->
    {#if source.origin === 'url'}
      <span class="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-700
                   dark:bg-amber-900/30 dark:text-amber-400">
        {m.search_origin_xc()}
      </span>
    {:else if source.origin === 's3'}
      <span class="shrink-0 rounded bg-emerald-100 px-1.5 py-0.5 text-xs font-medium text-emerald-700
                   dark:bg-emerald-900/30 dark:text-emerald-400">
        {m.search_source_s3()}
      </span>
    {:else}
      <span class="shrink-0 rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-600 dark:bg-stone-700">
        {m.search_origin_upload()}
      </span>
    {/if}

    <!-- Edit Clip button (hidden in readonly mode or for S3 sources) -->
    {#if !readonly && source.origin !== 's3'}
      <button
        type="button"
        class="shrink-0 transition-colors
               {showEditor
                 ? 'text-primary-600 hover:text-primary-700 dark:text-primary-400'
                 : 'text-stone-400 hover:text-primary-600 dark:hover:text-primary-400'}"
        onclick={showEditor ? closeEditor : openEditor}
        disabled={isLoadingAudio}
        aria-label={showEditor ? m.search_clip_editor_close() : m.search_edit_clip()}
        title={showEditor ? m.search_clip_editor_close() : m.search_edit_clip()}
      >
        {#if isLoadingAudio}
          <svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="12" cy="12" r="10" stroke-opacity="0.25" />
            <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
          </svg>
        {:else}
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="6" cy="6" r="3" />
            <circle cx="6" cy="18" r="3" />
            <path d="M20 4 8.12 15.88M14.47 14.48 20 20M8.12 8.12 12 12" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        {/if}
      </button>
    {/if}

    <!-- Remove button (hidden in readonly mode) -->
    {#if !readonly}
      <button
        type="button"
        class="shrink-0 text-stone-300 transition-colors hover:text-stone-500"
        onclick={onRemove}
        aria-label="Remove source"
      >
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    {/if}
  </div>

  <!-- Loading audio indicator -->
  {#if isLoadingAudio}
    <div class="flex items-center gap-2 border-t border-stone-200 px-3 py-2 dark:border-stone-700">
      <div class="h-4 w-4 animate-spin rounded-full border-2 border-stone-300 border-t-primary-500"></div>
      <span class="text-xs text-stone-500">{m.search_loading_audio()}</span>
    </div>
  {/if}

  <!-- Fetch error -->
  {#if fetchAudioError}
    <div class="border-t border-stone-200 px-3 py-2 dark:border-stone-700">
      <p class="text-xs text-danger">{fetchAudioError}</p>
    </div>
  {/if}

  <!-- Inline SpectrogramClipEditor -->
  {#if showEditor && editorAudioData}
    <div class="border-t border-stone-200 px-3 pt-2 pb-3 dark:border-stone-700">
      <div class="mb-2 flex items-center justify-between">
        <p class="text-xs font-medium text-stone-600">
          {m.search_clip_editor_title()}
        </p>
        <button
          type="button"
          class="rounded bg-primary-600 px-2 py-1 text-xs font-medium text-white hover:bg-primary-700 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
          onclick={confirmClip}
        >
          {m.search_save_clip()}
        </button>
      </div>
      <SpectrogramClipEditor
        audioFile={editorAudioData}
        duration={editorDuration}
        sampleRate={editorSampleRate}
        modelName={modelName === 'perch' || modelName === 'birdnet' ? modelName : 'perch'}
        startTime={editorStart}
        endTime={editorEnd}
        onRangeChange={handleEditorRangeChange}
      />
    </div>
  {/if}

  <!-- Readonly spectrogram viewer -->
  {#if readonly}
    {#if isLoadingSpectrogram}
      <div class="flex items-center gap-2 border-t border-stone-200 px-3 py-3 dark:border-stone-700">
        <div class="h-4 w-4 animate-spin rounded-full border-2 border-stone-300 border-t-primary-600"></div>
        <span class="text-xs text-stone-400">Loading spectrogram...</span>
      </div>
    {/if}
    {#if spectrogramLoadError}
      <div class="border-t border-stone-200 px-3 py-2 dark:border-stone-700">
        <p class="text-xs text-danger">{spectrogramLoadError}</p>
      </div>
    {/if}
    {#if showSpectrogram && spectrogramAudioData}
      <div class="border-t border-stone-200 px-3 pt-2 pb-3 dark:border-stone-700">
        <SpectrogramViewer
          audioData={spectrogramAudioData}
          duration={spectrogramDuration}
          sampleRate={spectrogramSampleRate}
          startTime={source.start_time ?? 0}
          endTime={source.end_time ?? spectrogramDuration}
          height={100}
        />
      </div>
    {/if}
  {/if}
</div>
