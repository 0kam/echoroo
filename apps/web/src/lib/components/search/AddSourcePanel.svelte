<script lang="ts">
  /**
   * AddSourcePanel - Panel within a SpeciesCard for adding a new reference sound.
   *
   * Phase 1: Upload File tab only. Provides a drag-drop zone, file validation,
   * audio decoding via Web Audio API, SpectrogramClipEditor integration, and
   * an optional label input before confirming.
   */

  import * as m from '$lib/paraglide/messages.js';
  import type { SoundSource } from '$lib/types/search';
  import { generateId } from '$lib/utils/id';
  import SpectrogramClipEditor from './SpectrogramClipEditor.svelte';
  import XenoCantoSearchPanel from './XenoCantoSearchPanel.svelte';

  interface Props {
    modelName: string;
    /** Scientific name of the species (pre-filled into Xeno-canto search) */
    scientificName: string;
    /** Project ID passed to Xeno-canto search API */
    projectId: string;
    /** Called with a single source (upload) or an array of sources (Xeno-canto multi-select) */
    onAdd: (sources: SoundSource | SoundSource[]) => void;
    onCancel: () => void;
  }

  let { modelName, scientificName, projectId, onAdd, onCancel }: Props = $props();

  // Active tab: 'upload' or 'xeno-canto'
  let activeTab = $state<'upload' | 'xeno-canto'>('upload');

  // File input DOM reference
  let fileInput: HTMLInputElement | undefined = $state();

  // Drop zone state
  let isDragging = $state(false);

  // Selected file and decoded audio metadata
  let selectedFile = $state<File | null>(null);
  let audioDuration = $state(0);
  let audioSampleRate = $state(48000);
  let decodeError = $state<string | null>(null);
  let isDecoding = $state(false);

  // Clip range (defaults to full audio)
  let clipStart = $state(0);
  let clipEnd = $state(0);

  // Optional label
  let label = $state('');

  // Validation constants
  const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
  const ACCEPTED_EXTENSIONS = ['.wav', '.flac', '.mp3', '.ogg'];

  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function formatDuration(seconds: number): string {
    return seconds.toFixed(1);
  }

  function isValidFile(file: File): string | null {
    const lowerName = file.name.toLowerCase();
    const hasValidExt = ACCEPTED_EXTENSIONS.some((ext) => lowerName.endsWith(ext));
    if (!hasValidExt) {
      return `Unsupported format. Please use ${ACCEPTED_EXTENSIONS.join(', ')}.`;
    }
    if (file.size > MAX_FILE_SIZE) {
      return `File exceeds the 10 MB size limit (${formatFileSize(file.size)}).`;
    }
    return null;
  }

  async function processFile(file: File) {
    const validationError = isValidFile(file);
    if (validationError) {
      decodeError = validationError;
      return;
    }

    selectedFile = file;
    decodeError = null;
    isDecoding = true;

    try {
      const arrayBuffer = await file.arrayBuffer();
      const ctx = new AudioContext();
      const buffer = await ctx.decodeAudioData(arrayBuffer.slice(0));

      audioDuration = buffer.duration;
      audioSampleRate = buffer.sampleRate;
      clipStart = 0;
      clipEnd = buffer.duration;

      await ctx.close();
    } catch (err) {
      decodeError = err instanceof Error ? err.message : 'Failed to decode audio file.';
      selectedFile = null;
    } finally {
      isDecoding = false;
    }
  }

  function handleFileSelect(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      void processFile(file);
    }
    // Reset input so the same file can be selected again
    input.value = '';
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault();
    isDragging = true;
  }

  function handleDragLeave() {
    isDragging = false;
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    isDragging = false;
    const file = e.dataTransfer?.files?.[0];
    if (file) {
      void processFile(file);
    }
  }

  function clearFile() {
    selectedFile = null;
    audioDuration = 0;
    audioSampleRate = 48000;
    clipStart = 0;
    clipEnd = 0;
    decodeError = null;
    label = '';
  }

  function handleAdd() {
    if (!selectedFile) return;

    const source: SoundSource = {
      id: generateId(),
      origin: 'upload',
      file: selectedFile,
      label: label.trim() || undefined,
      start_time: clipStart === 0 ? undefined : clipStart,
      end_time: clipEnd === audioDuration ? undefined : clipEnd,
      duration: audioDuration,
      sample_rate: audioSampleRate,
    };

    onAdd(source);

    // Reset state
    clearFile();
  }

  function handleRangeChange(start: number, end: number) {
    clipStart = start;
    clipEnd = end;
  }
</script>

<div class="border-t border-stone-200 px-3 py-3 dark:border-stone-700">
  <!-- Tab selector -->
  <div class="mb-3 flex gap-1">
    <button
      type="button"
      onclick={() => (activeTab = 'upload')}
      class="rounded px-3 py-1.5 text-sm font-medium transition-colors
             {activeTab === 'upload'
               ? 'bg-stone-700 text-white dark:bg-stone-600'
               : 'border border-stone-300 bg-white text-stone-600 hover:bg-stone-50 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-400 dark:hover:bg-stone-700'}"
    >
      {m.search_upload_file()}
    </button>
    <button
      type="button"
      onclick={() => (activeTab = 'xeno-canto')}
      class="rounded px-3 py-1.5 text-sm font-medium transition-colors
             {activeTab === 'xeno-canto'
               ? 'bg-stone-700 text-white dark:bg-stone-600'
               : 'border border-stone-300 bg-white text-stone-600 hover:bg-stone-50 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-400 dark:hover:bg-stone-700'}"
    >
      {m.search_from_url()}
    </button>
  </div>

  <!-- Xeno-canto search panel -->
  {#if activeTab === 'xeno-canto'}
    <XenoCantoSearchPanel
      {scientificName}
      {projectId}
      onAdd={(sources) => {
        onAdd(sources);
      }}
    />
    <!-- Cancel button -->
    <div class="mt-3 flex justify-end">
      <button
        type="button"
        class="rounded-md px-3 py-1.5 text-sm text-stone-600 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-700"
        onclick={onCancel}
      >
        {m.search_cancel()}
      </button>
    </div>
  {/if}

  <!-- Upload content -->
  {#if activeTab === 'upload' && !selectedFile}
    <!-- Validation error -->
    {#if decodeError}
      <p class="mb-2 rounded bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
        {decodeError}
      </p>
    {/if}

    <!-- Drop zone -->
    <div
      role="button"
      tabindex="0"
      class="cursor-pointer rounded-lg border-2 border-dashed p-6 text-center transition-colors
             {isDragging
               ? 'border-primary-400 bg-primary-50 dark:bg-primary-950/20'
               : 'border-stone-300 hover:border-primary-400 dark:border-stone-600'}"
      ondragover={handleDragOver}
      ondragleave={handleDragLeave}
      ondrop={handleDrop}
      onclick={() => fileInput?.click()}
      onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && fileInput?.click()}
    >
      <!-- Cloud upload icon -->
      <svg class="mx-auto mb-2 h-8 w-8 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path d="M7 16a4 4 0 0 1-.88-7.903A5 5 0 1 1 15.9 6L16 6a5 5 0 0 1 1 9.9M15 13l-3-3m0 0-3 3m3-3v12" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <p class="text-sm text-stone-600 dark:text-stone-400">{m.search_drop_zone_text()}</p>
      <p class="mt-1 text-xs text-stone-400">
        {m.search_drop_zone_browse()} — {m.search_drop_zone_formats()}
      </p>
    </div>
    <input
      bind:this={fileInput}
      type="file"
      accept=".wav,.flac,.mp3,.ogg"
      class="hidden"
      onchange={handleFileSelect}
    />

  {:else if activeTab === 'upload' && selectedFile}
    <!-- Decoding spinner -->
    {#if isDecoding}
      <div class="flex items-center justify-center py-6">
        <div class="h-5 w-5 animate-spin rounded-full border-2 border-stone-300 border-t-primary-500"></div>
        <span class="ml-2 text-sm text-stone-500">Decoding audio...</span>
      </div>
    {:else}
      <!-- File info row -->
      <div class="mb-3 flex items-center justify-between rounded-lg bg-stone-50 px-3 py-2 dark:bg-stone-800/50">
        <span class="truncate text-sm text-stone-900 dark:text-stone-100">
          {selectedFile.name}
          <span class="ml-1 text-xs text-stone-400">
            ({formatDuration(audioDuration)}s, {formatFileSize(selectedFile.size)})
          </span>
        </span>
        <button
          type="button"
          class="ml-2 shrink-0 text-stone-400 hover:text-stone-600"
          onclick={clearFile}
          aria-label={m.search_clear_file()}
        >
          <!-- X icon -->
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Spectrogram Clip Editor -->
      <SpectrogramClipEditor
        audioFile={selectedFile}
        duration={audioDuration}
        sampleRate={audioSampleRate}
        modelName={modelName === 'perch' || modelName === 'birdnet' ? modelName : 'perch'}
        startTime={clipStart}
        endTime={clipEnd}
        onRangeChange={handleRangeChange}
      />

      <!-- Label input -->
      <div class="mt-3">
        <label
          for="source-label-input"
          class="mb-1 block text-sm text-stone-600 dark:text-stone-400"
        >
          {m.search_source_label()}
        </label>
        <input
          id="source-label-input"
          bind:value={label}
          type="text"
          class="w-full rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm
                 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-1
                 focus:ring-primary-500 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
          placeholder={m.search_source_label_placeholder()}
        />
      </div>

      <!-- Action buttons -->
      <div class="mt-3 flex justify-end gap-2">
        <button
          type="button"
          class="rounded-md px-3 py-1.5 text-sm text-stone-600 hover:bg-stone-100 dark:text-stone-400 dark:hover:bg-stone-700"
          onclick={onCancel}
        >
          {m.search_cancel()}
        </button>
        <button
          type="button"
          class="rounded-md bg-primary-600 px-3 py-1.5 text-sm font-medium text-white
                 hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
          onclick={handleAdd}
          disabled={!selectedFile || isDecoding}
        >
          {m.search_add_source()}
        </button>
      </div>
    {/if}
  {/if}
</div>
