<script lang="ts">
  /**
   * SourceCard - Compact horizontal card for a single reference sound in the source list.
   *
   * Displays file name/label, clip range, duration, origin badge, and a play/stop button.
   * Audio playback uses the Web Audio API to play the selected clip range.
   *
   * Supports an inline SpectrogramClipEditor that can be opened with the "Edit Clip" button.
   * For upload sources the audio_data / file is used directly; for XC/URL sources the audio
   * is fetched from the backend proxy before opening the editor.
   */

  import { onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages.js';
  import type { SoundSource } from '$lib/types/search';
  import { fetchXenoCantoAudio } from '$lib/api/search';
  import SpectrogramClipEditor from './SpectrogramClipEditor.svelte';
  import SpectrogramViewer from './SpectrogramViewer.svelte';

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

  // ============================================================
  // Playback state (upload sources - Web Audio API)
  // ============================================================
  let isPlaying = $state(false);
  let audioCtx: AudioContext | null = null;
  let sourceNode: AudioBufferSourceNode | null = null;
  let decodedBuffer: AudioBuffer | null = null;
  let animHandle: number | null = null;

  // ============================================================
  // Playback state (URL / S3 sources - HTML Audio element)
  // ============================================================
  let urlAudio = $state<HTMLAudioElement | null>(null);
  let isUrlPlaying = $state(false);
  let urlAudioError = $state(false);

  // ============================================================
  // Clip editor state
  // ============================================================
  let showEditor = $state(false);
  let isLoadingAudio = $state(false);
  let fetchAudioError = $state<string | null>(null);
  /** Audio data (ArrayBuffer) ready to pass to SpectrogramClipEditor */
  let editorAudioData = $state<ArrayBuffer | null>(null);
  /** Duration (seconds) for the editor – derived from decoded audio */
  let editorDuration = $state(0);
  /** Sample rate for the editor */
  let editorSampleRate = $state(48000);

  // ============================================================
  // Readonly spectrogram viewer state
  // ============================================================
  /** Whether the inline spectrogram viewer is expanded (readonly mode only) */
  let showSpectrogram = $state(false);
  /** Audio data loaded for readonly spectrogram display */
  let spectrogramAudioData = $state<ArrayBuffer | null>(null);
  /** Duration reported from decoded audio for the viewer */
  let spectrogramDuration = $state(0);
  /** Sample rate for the spectrogram viewer */
  let spectrogramSampleRate = $state(48000);
  /** Whether we are currently fetching audio for the readonly viewer */
  let isLoadingSpectrogram = $state(false);
  /** Error message if spectrogram audio could not be loaded */
  let spectrogramLoadError = $state<string | null>(null);

  // Local mutable clip times that reflect pending edits before confirmation
  let editorStart = $state(source.start_time ?? 0);
  let editorEnd = $state(source.end_time ?? (source.duration ?? 0));

  // ============================================================
  // Upload playback helpers
  // ============================================================

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

  // ============================================================
  // URL playback helpers
  // ============================================================

  function toggleUrlPlay() {
    if (isUrlPlaying) {
      urlAudio?.pause();
      isUrlPlaying = false;
      return;
    }

    urlAudioError = false;

    if (!urlAudio) {
      // Use streamUrl for S3 sources, source_url for XC/URL sources
      const url = source.origin === 's3' ? source.streamUrl : source.source_url;
      if (!url) return;
      const audio = new Audio(url);
      audio.onended = () => {
        isUrlPlaying = false;
      };
      audio.onerror = () => {
        urlAudioError = true;
        isUrlPlaying = false;
      };
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
    try {
      sourceNode?.stop();
    } catch {
      // Already stopped
    }
    sourceNode = null;
    isPlaying = false;
  }

  // ============================================================
  // Readonly spectrogram helpers
  // ============================================================

  /**
   * Toggle the readonly spectrogram viewer. On first open, fetch the audio
   * from the appropriate source and decode it to get duration/sampleRate.
   */
  async function toggleSpectrogram() {
    if (showSpectrogram) {
      showSpectrogram = false;
      return;
    }

    // If audio is already loaded, just show it
    if (spectrogramAudioData) {
      showSpectrogram = true;
      return;
    }

    spectrogramLoadError = null;
    isLoadingSpectrogram = true;

    try {
      let arrayBuffer: ArrayBuffer;

      if (source.origin === 'upload') {
        // Uploaded file: use audio_data or read from File object
        if (source.audio_data) {
          arrayBuffer = source.audio_data;
        } else if (source.file) {
          arrayBuffer = await source.file.arrayBuffer();
        } else {
          throw new Error('No audio data available');
        }
      } else if (source.origin === 's3' && source.streamUrl) {
        // S3-persisted source: fetch the stream URL
        const response = await fetch(source.streamUrl, { credentials: 'include' });
        if (!response.ok) {
          throw new Error(`Failed to fetch audio: ${response.status}`);
        }
        arrayBuffer = await response.arrayBuffer();
      } else if (source.origin === 'url' && source.xc_id) {
        // Xeno-canto source: fetch via backend proxy
        arrayBuffer = await fetchXenoCantoAudio(projectId, source.xc_id);
      } else {
        throw new Error('No audio source available');
      }

      // Decode to extract duration and sample rate
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

  // ============================================================
  // Clip editor helpers
  // ============================================================

  async function openEditor() {
    fetchAudioError = null;

    if (source.origin === 'upload') {
      // For upload sources: use existing audio_data or read from File
      try {
        isLoadingAudio = true;
        let arrayBuffer: ArrayBuffer;
        if (source.audio_data) {
          arrayBuffer = source.audio_data;
        } else if (source.file) {
          arrayBuffer = await source.file.arrayBuffer();
        } else {
          fetchAudioError = 'No audio data available';
          isLoadingAudio = false;
          return;
        }

        // Decode to get duration and sample rate
        const ctx = new AudioContext();
        const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0));
        editorDuration = decoded.duration;
        editorSampleRate = decoded.sampleRate;
        await ctx.close();

        editorAudioData = arrayBuffer;
      } catch (err) {
        fetchAudioError = err instanceof Error ? err.message : m.search_fetch_audio_error();
        isLoadingAudio = false;
        return;
      }
    } else {
      // For XC/URL sources: fetch via backend proxy
      if (!source.xc_id) {
        fetchAudioError = 'No Xeno-canto ID available';
        isLoadingAudio = false;
        return;
      }
      try {
        isLoadingAudio = true;
        const arrayBuffer = await fetchXenoCantoAudio(projectId, source.xc_id);

        // Decode to get duration and sample rate
        const ctx = new AudioContext();
        const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0));
        editorDuration = decoded.duration;
        editorSampleRate = decoded.sampleRate;
        await ctx.close();

        editorAudioData = arrayBuffer;
      } catch (err) {
        fetchAudioError = err instanceof Error ? err.message : m.search_fetch_audio_error();
        isLoadingAudio = false;
        return;
      }
    }

    // Initialise editor clip bounds from current source values
    editorStart = source.start_time ?? 0;
    editorEnd = source.end_time ?? editorDuration;

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

  // ============================================================
  // Derived display values
  // ============================================================

  let displayName = $derived(
    source.label || source.file?.name || source.xc_id || 'Reference'
  );

  /** Whether this source plays via HTML Audio (URL or S3 streaming) */
  let isStreamingSource = $derived(source.origin === 'url' || source.origin === 's3');

  let clipInfo = $derived(() => {
    if (source.start_time != null && source.end_time != null) {
      const dur = source.end_time - source.start_time;
      return `${source.start_time.toFixed(1)}s–${source.end_time.toFixed(1)}s (${dur.toFixed(1)}s)`;
    } else if (source.duration != null) {
      return `${source.duration.toFixed(1)}s (${m.search_source_full()})`;
    }
    return '';
  });

  /** Whether the source has a non-default clip range set */
  let hasClipRange = $derived(source.start_time != null || source.end_time != null);

  // ============================================================
  // Cleanup
  // ============================================================

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
    {#if isStreamingSource}
      <button
        type="button"
        class="shrink-0 transition-colors
               {urlAudioError
                 ? 'text-red-400 hover:text-red-500'
                 : isUrlPlaying
                   ? 'text-primary-600 hover:text-primary-700 dark:text-primary-400'
                   : 'text-stone-500 hover:text-primary-600'}"
        onclick={toggleUrlPlay}
        aria-label={isUrlPlaying ? m.search_clip_stop() : m.search_clip_play_selection()}
        title={urlAudioError ? 'Playback failed' : isUrlPlaying ? 'Pause' : 'Play preview'}
      >
        {#if urlAudioError}
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 8v4m0 4h.01" stroke-linecap="round" />
          </svg>
        {:else if isUrlPlaying}
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <rect x="6" y="4" width="4" height="16" rx="1" />
            <rect x="14" y="4" width="4" height="16" rx="1" />
          </svg>
        {:else}
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86A1 1 0 0 0 8 5.14z" />
          </svg>
        {/if}
      </button>
      {#if source.origin === 'url' && source.xc_id}
        <a
          href="https://xeno-canto.org/{source.xc_id}"
          target="_blank"
          rel="noopener noreferrer"
          class="shrink-0 text-stone-400 transition-colors hover:text-primary-600"
          title={m.search_xc_listen()}
          aria-label={m.search_xc_listen()}
        >
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </a>
      {/if}
    {:else}
      <button
        type="button"
        class="shrink-0 text-stone-500 transition-colors hover:text-primary-600"
        onclick={togglePlay}
        aria-label={isPlaying ? m.search_clip_stop() : m.search_clip_play_selection()}
      >
        {#if isPlaying}
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <rect x="6" y="6" width="12" height="12" rx="1" />
          </svg>
        {:else}
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86A1 1 0 0 0 8 5.14z" />
          </svg>
        {/if}
      </button>
    {/if}

    <!-- Info -->
    <div class="min-w-0 flex-1">
      {#if readonly}
        <button
          type="button"
          class="truncate text-sm font-medium transition-colors
                 {showSpectrogram ? 'text-primary-600 dark:text-primary-400' : 'text-stone-900 hover:text-primary-600 dark:text-stone-100 dark:hover:text-primary-400'}
                 {isLoadingSpectrogram ? 'animate-pulse' : ''}"
          onclick={toggleSpectrogram}
          disabled={isLoadingSpectrogram}
          title={showSpectrogram ? 'Hide spectrogram' : 'Show spectrogram'}
        >
          {displayName}
        </button>
      {:else}
        <p class="truncate text-sm text-stone-900 dark:text-stone-100">{displayName}</p>
      {/if}
      {#if source.origin === 'url'}
        <p class="truncate text-xs text-stone-400">
          {[source.recording_type, source.quality ? `Q:${source.quality}` : null, source.recordist, source.location]
            .filter(Boolean)
            .join(' · ')}
        </p>
        {#if hasClipRange}
          <p class="text-xs text-primary-600 dark:text-primary-400">
            {m.search_clip_range({ start: (source.start_time ?? 0).toFixed(1) + 's', end: (source.end_time ?? 0).toFixed(1) + 's' })}
          </p>
        {/if}
      {:else}
        <p class="text-xs text-stone-400">{clipInfo()}</p>
      {/if}
    </div>

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
      <span class="shrink-0 rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-600 dark:bg-stone-700 dark:text-stone-300">
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
          <!-- Spinner -->
          <svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="12" cy="12" r="10" stroke-opacity="0.25" />
            <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
          </svg>
        {:else}
          <!-- Scissors icon -->
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="6" cy="6" r="3" />
            <circle cx="6" cy="18" r="3" />
            <path d="M20 4 8.12 15.88M14.47 14.48 20 20M8.12 8.12 12 12" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        {/if}
      </button>
    {/if}

    <!-- Spectrogram toggle button (readonly mode only) - REMOVED, use displayName click instead -->
    {#if readonly && false}
      <button
        type="button"
        class="shrink-0 transition-colors
               {showSpectrogram
                 ? 'text-primary-600 hover:text-primary-700 dark:text-primary-400'
                 : 'text-stone-400 hover:text-primary-600 dark:hover:text-primary-400'}"
        onclick={toggleSpectrogram}
        disabled={isLoadingSpectrogram}
        aria-label={showSpectrogram ? 'Hide spectrogram' : 'Show spectrogram'}
        title={showSpectrogram ? 'Hide spectrogram' : 'Show spectrogram'}
      >
        {#if isLoadingSpectrogram}
          <!-- Loading spinner -->
          <svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="12" cy="12" r="10" stroke-opacity="0.25" />
            <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
          </svg>
        {:else}
          <!-- Spectrogram / waveform icon -->
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <rect x="3" y="8" width="2" height="8" rx="1" />
            <rect x="7" y="5" width="2" height="14" rx="1" />
            <rect x="11" y="3" width="2" height="18" rx="1" />
            <rect x="15" y="6" width="2" height="12" rx="1" />
            <rect x="19" y="9" width="2" height="6" rx="1" />
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
      <p class="text-xs text-red-500 dark:text-red-400">{fetchAudioError}</p>
    </div>
  {/if}

  <!-- Inline SpectrogramClipEditor -->
  {#if showEditor && editorAudioData}
    <div class="border-t border-stone-200 px-3 pt-2 pb-3 dark:border-stone-700">
      <div class="mb-2 flex items-center justify-between">
        <p class="text-xs font-medium text-stone-600 dark:text-stone-400">
          {m.search_clip_editor_title()}
        </p>
        <button
          type="button"
          class="rounded bg-primary-600 px-2 py-1 text-xs font-medium text-white hover:bg-primary-700"
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

  <!-- Readonly spectrogram viewer (shown when spectrogram toggle is active) -->
  {#if readonly}
    {#if spectrogramLoadError}
      <div class="border-t border-stone-200 px-3 py-2 dark:border-stone-700">
        <p class="text-xs text-red-500 dark:text-red-400">{spectrogramLoadError}</p>
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
