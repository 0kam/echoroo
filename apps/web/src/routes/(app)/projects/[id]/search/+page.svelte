<script lang="ts">
  /**
   * Similarity search page.
   *
   * Allows users to upload an audio clip and find similar sounds
   * across all recordings in the project using ML embeddings.
   */

  import { page } from '$app/stores';
  import { createQuery } from '@tanstack/svelte-query';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import { fetchDatasets } from '$lib/api/datasets';
  import { searchSimilarByAudio, fetchEmbeddingStats } from '$lib/api/search';
  import type { SimilarityResult, SimilaritySearchResponse, EmbeddingStats } from '$lib/types/search';
  import type { Dataset } from '$lib/types/data';

  const projectId = $derived($page.params.id as string);

  // ============================================
  // Search form state (Svelte 5 runes)
  // ============================================

  let selectedFile = $state<File | null>(null);
  let modelName = $state('perch');
  let minSimilarity = $state(0.5);
  let limit = $state(20);
  let datasetFilter = $state('');
  let isDragging = $state(false);

  // ============================================
  // Search result state
  // ============================================

  let isSearching = $state(false);
  let searchError = $state<string | null>(null);
  let searchResults = $state<SimilaritySearchResponse | null>(null);

  // ============================================
  // Audio playback state
  // ============================================

  let playingId = $state<string | null>(null);
  let audioElement = $state<HTMLAudioElement | null>(null);

  // ============================================
  // Datasets query
  // ============================================

  const datasetsQuery = $derived(
    createQuery({
      queryKey: ['datasets', projectId],
      queryFn: () => fetchDatasets(projectId, { page_size: 100 }),
      enabled: !!projectId,
    })
  );

  // ============================================
  // Embedding stats query
  // ============================================

  const statsQuery = $derived(
    createQuery({
      queryKey: ['embedding-stats', projectId],
      queryFn: () => fetchEmbeddingStats(projectId),
      enabled: !!projectId,
    })
  );

  // ============================================
  // File handling
  // ============================================

  function handleFileSelect(event: Event) {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      selectedFile = input.files[0] ?? null;
      // Reset previous results when a new file is selected
      searchResults = null;
      searchError = null;
    }
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    isDragging = false;
    const file = event.dataTransfer?.files[0];
    if (file) {
      selectedFile = file;
      searchResults = null;
      searchError = null;
    }
  }

  function handleDragOver(event: DragEvent) {
    event.preventDefault();
    isDragging = true;
  }

  function handleDragLeave() {
    isDragging = false;
  }

  // ============================================
  // Search execution
  // ============================================

  async function handleSearch() {
    if (!selectedFile) {
      searchError = m.search_error_no_file();
      return;
    }

    isSearching = true;
    searchError = null;
    searchResults = null;

    try {
      const params = {
        model_name: modelName,
        limit,
        min_similarity: minSimilarity,
        dataset_id: datasetFilter || undefined,
      };
      searchResults = await searchSimilarByAudio(projectId, selectedFile, params);
    } catch (err) {
      searchError = err instanceof Error ? err.message : m.search_error_search_failed();
    } finally {
      isSearching = false;
    }
  }

  // ============================================
  // Audio playback
  // ============================================

  /**
   * Build a presigned URL for a recording segment using the S3 proxy.
   * The backend provides the audio via the recording detail endpoint.
   */
  function getAudioUrl(recordingId: string, startTime: number, endTime: number): string {
    return `/api/v1/projects/${projectId}/recordings/${recordingId}/audio?start=${startTime}&end=${endTime}`;
  }

  function togglePlayback(result: SimilarityResult) {
    if (playingId === result.embedding_id) {
      // Stop current playback
      audioElement?.pause();
      audioElement = null;
      playingId = null;
    } else {
      // Stop any existing playback first
      audioElement?.pause();
      audioElement = null;
      playingId = null;

      // Start new playback
      const url = getAudioUrl(result.recording_id, result.start_time, result.end_time);
      const audio = new Audio(url);
      audio.addEventListener('ended', () => {
        if (playingId === result.embedding_id) {
          playingId = null;
          audioElement = null;
        }
      });
      audio.addEventListener('error', () => {
        if (playingId === result.embedding_id) {
          playingId = null;
          audioElement = null;
        }
      });
      audioElement = audio;
      playingId = result.embedding_id;
      audio.play().catch(() => {
        playingId = null;
        audioElement = null;
      });
    }
  }

  // ============================================
  // Formatting helpers
  // ============================================

  /**
   * Convert seconds to mm:ss display format.
   */
  function formatTime(seconds: number): string {
    const minutes = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  /**
   * Format similarity score as percentage.
   */
  function formatSimilarity(similarity: number): string {
    return `${(similarity * 100).toFixed(1)}%`;
  }

  /**
   * Get similarity badge color class based on score.
   */
  function getSimilarityClass(similarity: number): string {
    if (similarity >= 0.9) return 'bg-green-100 text-green-800';
    if (similarity >= 0.7) return 'bg-blue-100 text-blue-800';
    if (similarity >= 0.5) return 'bg-yellow-100 text-yellow-800';
    return 'bg-gray-100 text-gray-800';
  }

  /**
   * Get dataset name by ID from fetched datasets.
   */
  function getDatasetName(datasetId: string): string {
    const datasets = $datasetsQuery.data?.items ?? [];
    const found = datasets.find((d: Dataset) => d.id === datasetId);
    return found?.name ?? datasetId.slice(0, 8) + '…';
  }
</script>

<svelte:head>
  <title>{m.search_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-4xl space-y-6 px-6 py-8">
  <!-- Page header -->
  <div>
    <nav class="mb-2 flex items-center gap-2 text-sm text-gray-500">
      <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-gray-900">
        {m.search_breadcrumb_project()}
      </a>
      <span>/</span>
      <span class="font-medium text-gray-900">{m.search_title()}</span>
    </nav>
    <h1 class="text-2xl font-bold text-gray-900">{m.search_title()}</h1>
    <p class="mt-1 text-sm text-gray-500">{m.search_description()}</p>
  </div>

  <!-- Search form card -->
  <div class="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
    <div class="space-y-5">
      <!-- File upload area -->
      <div>
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="relative flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors {isDragging
            ? 'border-blue-400 bg-blue-50'
            : selectedFile
              ? 'border-green-400 bg-green-50'
              : 'border-gray-300 bg-gray-50 hover:border-gray-400 hover:bg-gray-100'}"
          ondrop={handleDrop}
          ondragover={handleDragOver}
          ondragleave={handleDragLeave}
          onclick={() => document.getElementById('audio-file-input')?.click()}
          role="button"
          tabindex="0"
          onkeydown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              document.getElementById('audio-file-input')?.click();
            }
          }}
          aria-label={m.search_upload_audio()}
        >
          <input
            id="audio-file-input"
            type="file"
            accept="audio/*"
            class="sr-only"
            onchange={handleFileSelect}
          />

          {#if selectedFile}
            <!-- File selected state -->
            <svg class="mb-2 h-8 w-8 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
            </svg>
            <p class="text-sm font-medium text-green-700">
              {m.search_selected_file({ filename: selectedFile.name })}
            </p>
            <p class="mt-1 text-xs text-green-600">
              {(selectedFile.size / 1024).toFixed(1)} KB
            </p>
          {:else}
            <!-- Empty state -->
            <svg class="mb-2 h-8 w-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p class="text-sm font-medium text-gray-700">{m.search_drop_audio()}</p>
            <p class="mt-1 text-xs text-gray-500">{m.search_audio_hint()}</p>
          {/if}
        </div>
      </div>

      <!-- Parameters row -->
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <!-- Model selector -->
        <div>
          <label for="model-select" class="mb-1 block text-xs font-medium text-gray-700">
            {m.search_select_model()}
          </label>
          <select
            id="model-select"
            bind:value={modelName}
            class="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="perch">Perch v2.0</option>
            <option value="birdnet">BirdNET v2.4</option>
          </select>
        </div>

        <!-- Min similarity slider -->
        <div>
          <label for="similarity-slider" class="mb-1 block text-xs font-medium text-gray-700">
            {m.search_min_similarity()}: {(minSimilarity * 100).toFixed(0)}%
          </label>
          <input
            id="similarity-slider"
            type="range"
            min="0"
            max="1"
            step="0.05"
            bind:value={minSimilarity}
            class="w-full accent-blue-600"
          />
        </div>

        <!-- Max results -->
        <div>
          <label for="limit-input" class="mb-1 block text-xs font-medium text-gray-700">
            {m.search_max_results()}
          </label>
          <input
            id="limit-input"
            type="number"
            min="1"
            max="100"
            bind:value={limit}
            class="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>

        <!-- Dataset filter -->
        <div>
          <label for="dataset-select" class="mb-1 block text-xs font-medium text-gray-700">
            {m.search_dataset_filter()}
          </label>
          <select
            id="dataset-select"
            bind:value={datasetFilter}
            class="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="">{m.search_all_datasets()}</option>
            {#each $datasetsQuery.data?.items ?? [] as dataset (dataset.id)}
              <option value={dataset.id}>{dataset.name}</option>
            {/each}
          </select>
        </div>
      </div>

      <!-- Error message -->
      {#if searchError}
        <div class="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
          {searchError}
        </div>
      {/if}

      <!-- Search button -->
      <div class="flex justify-end">
        <button
          onclick={handleSearch}
          disabled={isSearching || !selectedFile}
          class="flex items-center gap-2 rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {#if isSearching}
            <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            {m.search_searching()}
          {:else}
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            {m.search_button()}
          {/if}
        </button>
      </div>
    </div>
  </div>

  <!-- Results section -->
  {#if searchResults !== null}
    <div class="rounded-lg border border-gray-200 bg-white shadow-sm">
      <div class="flex items-center justify-between border-b border-gray-100 px-6 py-4">
        <h2 class="text-base font-semibold text-gray-900">{m.search_results()}</h2>
        <span class="text-sm text-gray-500">
          {m.search_results_count({ count: searchResults.total_results })}
        </span>
      </div>

      {#if searchResults.results.length === 0}
        <!-- No results -->
        <div class="flex flex-col items-center justify-center px-6 py-12 text-center">
          <svg class="mb-3 h-10 w-10 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
          </svg>
          <p class="text-sm font-medium text-gray-700">{m.search_no_results()}</p>
          <p class="mt-1 text-xs text-gray-400">{m.search_no_results_hint()}</p>
        </div>
      {:else}
        <!-- Results list -->
        <ul class="divide-y divide-gray-100">
          {#each searchResults.results as result (result.embedding_id)}
            <li class="px-6 py-4">
              <div class="flex items-start justify-between gap-4">
                <!-- Left: recording info -->
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <!-- Play button -->
                    <button
                      onclick={() => togglePlayback(result)}
                      class="flex-shrink-0 rounded-full p-1.5 text-gray-500 transition-colors hover:bg-gray-100 hover:text-blue-600"
                      title={playingId === result.embedding_id ? m.search_stop() : m.search_play()}
                      aria-label={playingId === result.embedding_id ? m.search_stop() : m.search_play()}
                    >
                      {#if playingId === result.embedding_id}
                        <!-- Stop icon -->
                        <svg class="h-5 w-5 text-blue-600" fill="currentColor" viewBox="0 0 24 24">
                          <rect x="6" y="6" width="12" height="12" rx="1" />
                        </svg>
                      {:else}
                        <!-- Play icon -->
                        <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M8 5v14l11-7z" />
                        </svg>
                      {/if}
                    </button>

                    <!-- Filename -->
                    <span class="truncate text-sm font-medium text-gray-900">
                      {result.recording_filename}
                    </span>
                  </div>

                  <!-- Metadata row -->
                  <div class="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-gray-500">
                    <!-- Time range -->
                    <span class="flex items-center gap-1">
                      <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      {formatTime(result.start_time)} – {formatTime(result.end_time)}
                    </span>

                    <!-- Dataset name -->
                    <span class="flex items-center gap-1">
                      <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                      </svg>
                      {getDatasetName(result.dataset_id)}
                    </span>
                  </div>
                </div>

                <!-- Right: similarity badge + link -->
                <div class="flex flex-shrink-0 flex-col items-end gap-2">
                  <!-- Similarity badge -->
                  <span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold {getSimilarityClass(result.similarity)}">
                    {formatSimilarity(result.similarity)}
                  </span>

                  <!-- View recording link -->
                  <a
                    href={localizeHref(`/projects/${projectId}/recordings/${result.recording_id}`)}
                    class="text-xs text-blue-600 hover:underline"
                  >
                    {m.search_view_recording()}
                  </a>
                </div>
              </div>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}

  <!-- Embedding stats section -->
  <div class="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
    <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-500">
      {m.search_embedding_stats()}
    </h2>

    {#if $statsQuery.isLoading}
      <div class="flex items-center gap-2 text-sm text-gray-400">
        <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        Loading...
      </div>
    {:else if $statsQuery.isError}
      <p class="text-sm text-red-500">Failed to load embedding statistics.</p>
    {:else if $statsQuery.data}
      {@const stats = $statsQuery.data as EmbeddingStats}
      {#if stats.total_count === 0}
        <!-- No embeddings -->
        <div class="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          {m.search_no_embeddings()}
        </div>
      {:else}
        <div class="flex flex-wrap gap-6">
          <!-- Total count -->
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-gray-400">
              {m.search_total_embeddings()}
            </p>
            <p class="mt-1 text-2xl font-bold text-gray-900">
              {stats.total_count.toLocaleString()}
            </p>
          </div>

          <!-- By model -->
          {#if Object.keys(stats.by_model).length > 0}
            <div>
              <p class="text-xs font-medium uppercase tracking-wider text-gray-400">
                {m.search_stats_by_model()}
              </p>
              <div class="mt-1 flex flex-wrap gap-2">
                {#each Object.entries(stats.by_model) as [model, count] (model)}
                  <span class="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800">
                    {model}: {count.toLocaleString()}
                  </span>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  </div>
</div>
