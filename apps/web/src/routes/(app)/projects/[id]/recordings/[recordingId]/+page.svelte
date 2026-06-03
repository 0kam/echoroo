<script lang="ts">
  import { page } from '$app/stores';
  import { browser } from '$app/environment';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { getRecording, updateRecording, deleteRecording, getDownloadUrl } from '$lib/api/recordings';
  import { goto } from '$app/navigation';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import AudioPlayer from '$lib/components/audio/AudioPlayer.svelte';
  import SpectrogramViewer from '$lib/components/audio/SpectrogramViewer.svelte';
  import SpectrogramSettings from '$lib/components/audio/SpectrogramSettings.svelte';
  import AudioFilterSettings from '$lib/components/audio/AudioFilterSettings.svelte';
  import PlaybackSpeedControl from '$lib/components/audio/PlaybackSpeedControl.svelte';
  import ViewportBar from '$lib/components/audio/ViewportBar.svelte';
  import ViewportToolbar from '$lib/components/audio/ViewportToolbar.svelte';
  import ScaleControls from '$lib/components/audio/ScaleControls.svelte';
  import ClipList from '$lib/components/data/ClipList.svelte';
  import ClipDetail from '$lib/components/data/ClipDetail.svelte';

  import {
    DEFAULT_SPECTROGRAM_SETTINGS,
    DEFAULT_AUDIO_SETTINGS,
    getSpeedOptions,
    type SpectrogramSettings as SpectrogramSettingsType,
    type AudioSettings,
    type SpectrogramWindow,
    type InteractionMode,
  } from '$lib/types/audio';
  import {
    getInitialViewingWindow,
    adjustWindowToBounds,
    centerWindowOn,
  } from '$lib/utils/viewport';
  import { untrack } from 'svelte';
  import type { Clip } from '$lib/types/data';
  import * as m from '$lib/paraglide/messages';

  // Route params
  let projectId = $derived($page.params.id as string);
  let recordingId = $derived($page.params.recordingId as string);

  // Recording query - only fetch on client side to avoid SSR fetch issues
  let recordingQuery = $derived(
    createQuery({
      queryKey: ['recording', projectId, recordingId],
      queryFn: () => getRecording(projectId, recordingId),
      enabled: browser && !!projectId && !!recordingId,
    })
  );

  // Spectrogram settings state
  let spectrogramSettings = $state<SpectrogramSettingsType>({ ...DEFAULT_SPECTROGRAM_SETTINGS });
  let audioSettings = $state<AudioSettings>({ ...DEFAULT_AUDIO_SETTINGS });

  // Interaction mode
  let interactionMode = $state<InteractionMode>('panning');

  // Viewport state
  let viewport = $state<SpectrogramWindow>({
    time: { min: 0, max: 20 },
    freq: { min: 0, max: 24000 },
  });

  // Viewport history stack for back navigation
  let viewportHistory: SpectrogramWindow[] = [];

  // Bounds derived from recording
  let bounds = $derived.by((): SpectrogramWindow => {
    const rec = $recordingQuery.data;
    if (!rec) return { time: { min: 0, max: 60 }, freq: { min: 0, max: 24000 } };
    return {
      time: { min: 0, max: rec.duration },
      freq: { min: 0, max: rec.samplerate / 2 },
    };
  });

  // Initialize viewport when recording loads
  $effect(() => {
    const rec = $recordingQuery.data;
    if (!rec) return;

    viewport = getInitialViewingWindow({
      startTime: 0,
      endTime: rec.duration,
      samplerate: rec.samplerate,
    });

    // Update samplerate directly to avoid read-write loop
    // (spreading audioSettings inside $effect would track it as a dependency,
    // causing an infinite reactive loop since each spread creates a new object)
    audioSettings.samplerate = rec.samplerate;
  });

  // Track previous scale values to compute relative zoom on change.
  // Initial values are captured once via untrack(); subsequent updates
  // happen inside the $effect below where we deliberately wrap the
  // assignment in untrack() to avoid re-triggering the effect.
  let prevTimeScale = $state(untrack(() => spectrogramSettings.time_scale));
  let prevFreqScale = $state(untrack(() => spectrogramSettings.freq_scale));

  // When time_scale or freq_scale changes, zoom the viewport relative to
  // its current size (not relative to the full recording bounds).
  $effect(() => {
    const timeScale = spectrogramSettings.time_scale;
    const freqScale = spectrogramSettings.freq_scale;

    const currentViewport = untrack(() => viewport);
    const currentBounds = untrack(() => bounds);
    const oldTimeScale = untrack(() => prevTimeScale);
    const oldFreqScale = untrack(() => prevFreqScale);

    // Skip if nothing changed (e.g. initial run)
    if (timeScale === oldTimeScale && freqScale === oldFreqScale) return;

    const currentDuration = currentViewport.time.max - currentViewport.time.min;
    const currentBandwidth = currentViewport.freq.max - currentViewport.freq.min;

    // Ratio: if scale went from 1x to 2x, shrink viewport to 1/2
    const newDuration = currentDuration * (oldTimeScale / timeScale);
    const newBandwidth = currentBandwidth * (oldFreqScale / freqScale);

    const timeCenter = (currentViewport.time.min + currentViewport.time.max) / 2;
    const freqCenter = (currentViewport.freq.min + currentViewport.freq.max) / 2;

    const proposed: SpectrogramWindow = {
      time: { min: timeCenter - newDuration / 2, max: timeCenter + newDuration / 2 },
      freq: { min: freqCenter - newBandwidth / 2, max: freqCenter + newBandwidth / 2 },
    };

    viewport = adjustWindowToBounds(proposed, currentBounds);

    // Update previous values (inside untrack to avoid re-triggering)
    untrack(() => {
      prevTimeScale = timeScale;
      prevFreqScale = freqScale;
    });
  });

  // Current audio time
  let currentTime = $state(0);

  // Speed options computed from recording sample rate
  let speedOptions = $derived.by(() => {
    const rec = $recordingQuery.data;
    if (!rec) return getSpeedOptions(48000);
    return getSpeedOptions(rec.samplerate);
  });

  // UI state
  let showSettings = $state(false);
  let showFilters = $state(false);
  let showEditModal = $state(false);
  let editNote = $state('');
  let editTimeExpansion = $state(1.0);
  let selectedClip = $state<Clip | null>(null);

  const queryClient = useQueryClient();

  const updateMut = createMutation({
    mutationFn: (data: { note?: string; time_expansion?: number }) =>
      updateRecording(projectId, recordingId, data),
    onSuccess: () => {
      showEditModal = false;
      queryClient.invalidateQueries({ queryKey: ['recording', projectId, recordingId] });
    },
  });

  const deleteMut = createMutation({
    mutationFn: () => deleteRecording(projectId, recordingId),
    onSuccess: () => {
      goto(localizeHref(`/projects/${projectId}/recordings`));
    },
  });

  // Viewport management
  function handleViewportChange(newViewport: SpectrogramWindow) {
    viewport = newViewport;
  }

  function handleViewportSave() {
    viewportHistory = [...viewportHistory, { ...viewport }];
  }

  function handleViewportBack() {
    if (viewportHistory.length > 0) {
      const prev = viewportHistory[viewportHistory.length - 1] as SpectrogramWindow;
      viewportHistory = viewportHistory.slice(0, -1);
      viewport = prev;
    }
  }

  function handleViewportReset() {
    const rec = $recordingQuery.data;
    if (!rec) return;
    viewportHistory = [];
    viewport = getInitialViewingWindow({
      startTime: 0,
      endTime: rec.duration,
      samplerate: rec.samplerate,
    });
  }

  function handleSeek(time: number) {
    currentTime = time;
    viewport = adjustWindowToBounds(
      centerWindowOn(viewport, { time }),
      bounds
    );
  }

  function handleTimeUpdate(time: number) {
    currentTime = time;
  }

  function handleKeyDown(e: KeyboardEvent) {
    switch (e.key.toLowerCase()) {
      case 'x':
        interactionMode = 'panning';
        break;
      case 'z':
        interactionMode = 'zooming';
        break;
      case 'b':
        handleViewportBack();
        break;
    }
  }

  // Edit modal
  function openEditModal() {
    const rec = $recordingQuery.data;
    if (!rec) return;
    editNote = rec.note ?? '';
    editTimeExpansion = rec.time_expansion;
    showEditModal = true;
  }

  function handleEditSubmit(e: Event) {
    e.preventDefault();
    $updateMut.mutate({ note: editNote, time_expansion: editTimeExpansion });
  }

  function handleDelete() {
    if (confirm(m.recording_detail_delete_confirm())) {
      $deleteMut.mutate();
    }
  }

  function handleClipSelect(clip: Clip) {
    selectedClip = clip;
  }

  function formatDuration(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.round((seconds % 1) * 10);
    return `${mins}:${secs.toString().padStart(2, '0')}.${ms}`;
  }

  function formatSamplerate(hz: number): string {
    if (hz >= 1000) return `${(hz / 1000).toFixed(1)} kHz`;
    return `${hz} Hz`;
  }
</script>

<svelte:window onkeydown={handleKeyDown} />

<div class="page">
  {#if $recordingQuery.isLoading}
    <div class="flex flex-col items-center justify-center py-20 gap-4">
      <div class="w-10 h-10 border-4 border-success border-t-transparent rounded-full animate-spin"></div>
      <p class="text-stone-500 text-sm">{m.recording_detail_loading()}</p>
    </div>

  {:else if $recordingQuery.error}
    <div class="flex flex-col items-center justify-center py-20 gap-4 bg-danger-light rounded-lg">
      <svg class="w-12 h-12 text-danger/60" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <p class="text-danger">Error: {$recordingQuery.error.message}</p>
    </div>

  {:else if $recordingQuery.data}
    {@const recording = $recordingQuery.data}

    <!-- Breadcrumb -->
    <nav class="flex items-center gap-2 text-sm mb-4 text-stone-500">
      <a href={localizeHref(`/projects/${projectId}/recordings`)} class="text-success hover:underline">
        {m.recording_detail_breadcrumb_recordings()}
      </a>
      <span>/</span>
      <span class="truncate text-stone-600 font-medium">
        {recording.filename}
      </span>
    </nav>

    <!-- Recording metadata row -->
    <div class="metadata-bar">
      <div class="metadata-chips">
        <span class="chip">
          <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          {formatDuration(recording.duration)}
        </span>
        <span class="chip">
          <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 18V5l12-2v13" />
            <circle cx="6" cy="18" r="3" />
            <circle cx="18" cy="16" r="3" />
          </svg>
          {formatSamplerate(recording.samplerate)}
        </span>
        <span class="chip">
          Ch {recording.channels}
        </span>
        {#if recording.bit_depth}
          <span class="chip">{recording.bit_depth}-bit</span>
        {/if}
        {#if recording.is_ultrasonic}
          <span class="chip chip-warning">{m.recording_detail_ultrasonic()}</span>
        {/if}
        {#if recording.datetime}
          <span class="chip">
            <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
              <line x1="16" y1="2" x2="16" y2="6" />
              <line x1="8" y1="2" x2="8" y2="6" />
              <line x1="3" y1="10" x2="21" y2="10" />
            </svg>
            {new Date(recording.datetime).toLocaleString(getLocale())}
          </span>
        {/if}
      </div>

      <!-- Action buttons -->
      <div class="flex gap-2">
        <a
          href={getDownloadUrl(projectId, recordingId)}
          download={recording.filename}
          class="action-btn"
          title="Download original file"
        >
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          {m.recording_detail_download()}
        </a>
        <button type="button" class="action-btn" onclick={openEditModal}>
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
          </svg>
          {m.recording_detail_edit()}
        </button>
        <button type="button" class="action-btn action-btn-danger" onclick={handleDelete}>
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
          {m.recording_detail_delete()}
        </button>
      </div>
    </div>

    <!-- Main viewer area -->
    <div class="viewer-area">
      <!-- Toolbar row -->
      <div class="toolbar-row">
        <ViewportToolbar
          mode={interactionMode}
          onReset={handleViewportReset}
          onBack={handleViewportBack}
          onPan={() => (interactionMode = 'panning')}
          onZoom={() => (interactionMode = 'zooming')}
        />

        <div class="flex items-center gap-4 ml-auto">
          <!-- Scale controls -->
          <ScaleControls
            settings={spectrogramSettings}
            onChange={(s) => (spectrogramSettings = s)}
          />

          <!-- Settings toggle -->
          <button
            type="button"
            class="action-btn {showSettings ? 'action-btn-active' : ''}"
            onclick={() => (showSettings = !showSettings)}
            title="Spectrogram settings"
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.07 4.93l-1.41 1.41M6.34 17.66l-1.41 1.41M2 12h2M20 12h2M6.34 6.34L4.93 4.93M17.66 17.66l1.41 1.41M12 2v2M12 20v2" />
            </svg>
            {m.recording_detail_settings()}
          </button>

          <!-- Filter toggle -->
          <button
            type="button"
            class="action-btn {showFilters ? 'action-btn-active' : ''}"
            onclick={() => (showFilters = !showFilters)}
            title="Audio filter settings"
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
            </svg>
            {m.recording_detail_filters()}
          </button>
        </div>
      </div>

      <!-- Audio Player row -->
      <div class="player-row">
        <AudioPlayer
          {projectId}
          {recordingId}
          duration={recording.duration}
          speed={audioSettings.speed}
          {speedOptions}
          samplerate={recording.samplerate}
          {viewport}
          {bounds}
          seekTo={currentTime}
          onViewportChange={handleViewportChange}
          onTimeUpdate={handleTimeUpdate}
          onSeek={handleSeek}
          onSpeedChange={(s) => (audioSettings = { ...audioSettings, speed: s })}
        />

        <PlaybackSpeedControl
          speed={audioSettings.speed}
          samplerate={recording.samplerate}
          onChange={(s) => (audioSettings = { ...audioSettings, speed: s })}
        />
      </div>

      <!-- Settings panels (collapsible) -->
      {#if showSettings}
        <div class="settings-row">
          <SpectrogramSettings
            settings={spectrogramSettings}
            onChange={(s) => (spectrogramSettings = s)}
          />
        </div>
      {/if}

      {#if showFilters}
        <div class="settings-row">
          <AudioFilterSettings
            settings={audioSettings}
            samplerate={recording.samplerate}
            onChange={(s) => (audioSettings = s)}
          />
        </div>
      {/if}

      <!-- Spectrogram Canvas -->
      <SpectrogramViewer
        {recording}
        {projectId}
        spectrogramSettings={spectrogramSettings}
        {viewport}
        {bounds}
        {currentTime}
        {interactionMode}
        onViewportChange={handleViewportChange}
        onViewportSave={handleViewportSave}
        onSeek={handleSeek}
        onModeChange={(m) => (interactionMode = m)}
      />

      <!-- Viewport bar -->
      <ViewportBar
        {viewport}
        {bounds}
        onViewportChange={handleViewportChange}
        onViewportSave={handleViewportSave}
      />

      <!-- Keyboard shortcut hints -->
      <div class="shortcut-hints">
        <span><kbd>X</kbd> {m.recording_detail_shortcut_pan()}</span>
        <span><kbd>Z</kbd> {m.recording_detail_shortcut_zoom()}</span>
        <span><kbd>B</kbd> {m.recording_detail_shortcut_back()}</span>
        <span><kbd>Space</kbd> {m.recording_detail_shortcut_play_pause()}</span>
        <span><kbd>Scroll</kbd> {m.recording_detail_shortcut_navigate()}</span>
        <span><kbd>Ctrl+Scroll</kbd> {m.recording_detail_shortcut_expand()}</span>
        <span><kbd>Alt+Scroll</kbd> {m.recording_detail_shortcut_zoom()}</span>
        <span><kbd>DblClick</kbd> Seek</span>
      </div>
    </div>

    <!-- Notes section -->
    {#if recording.note}
      <div class="notes-section">
        <h4 class="notes-title">{m.recording_detail_notes_title()}</h4>
        <p class="notes-content">{recording.note}</p>
      </div>
    {/if}

    <!-- Clips section -->
    <section class="clips-section" aria-label="Recording clips">
      <ClipList
        {projectId}
        {recordingId}
        selectedClipId={selectedClip?.id ?? null}
        onSelect={handleClipSelect}
      />

      {#if selectedClip}
        <div class="clip-detail-panel">
          <ClipDetail {projectId} {recordingId} clip={selectedClip} />
        </div>
      {/if}
    </section>
  {/if}

  <!-- Edit Modal -->
  {#if showEditModal}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onclick={() => (showEditModal = false)}
    >
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="bg-surface-card rounded-lg shadow-xl p-6 w-full max-w-md"
        onclick={(e) => e.stopPropagation()}
      >
        <h3 class="text-lg font-semibold text-stone-800 mb-4">{m.recording_detail_edit_modal_title()}</h3>
        <form onsubmit={handleEditSubmit}>
          <div class="space-y-4 mb-6">
            <div>
              <label for="time-expansion" class="block text-sm font-medium text-stone-700 mb-1">
                {m.recording_detail_time_expansion_label()}
              </label>
              <input
                id="time-expansion"
                type="number"
                step="0.1"
                min="0.1"
                max="100"
                bind:value={editTimeExpansion}
                class="w-full px-3 py-2 border border-stone-300 rounded-md text-sm bg-surface-card focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
              <p class="mt-1 text-xs text-stone-500">{m.recording_detail_time_expansion_hint()}</p>
            </div>
            <div>
              <label for="note" class="block text-sm font-medium text-stone-700 mb-1">
                {m.recording_detail_notes_label()}
              </label>
              <textarea
                id="note"
                bind:value={editNote}
                rows="3"
                class="w-full px-3 py-2 border border-stone-300 rounded-md text-sm bg-surface-card focus:outline-none focus:ring-2 focus:ring-primary-500"
              ></textarea>
            </div>
          </div>
          <div class="flex justify-end gap-3">
            <button
              type="button"
              onclick={() => (showEditModal = false)}
              class="px-4 py-2 text-sm font-medium border border-stone-300 rounded-md hover:bg-stone-50"
            >
              {m.recording_detail_cancel()}
            </button>
            <button
              type="submit"
              disabled={$updateMut.isPending}
              class="px-4 py-2 text-sm font-medium bg-success text-white rounded-md hover:opacity-90 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {$updateMut.isPending ? m.recording_detail_saving() : m.recording_detail_save()}
            </button>
          </div>
        </form>
      </div>
    </div>
  {/if}
</div>

<style>
  .page {
    padding: 1.5rem;
    max-width: 1600px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .metadata-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .metadata-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.25rem 0.625rem;
    background: #f3f4f6;
    color: rgb(var(--stone-700));
    border-radius: 9999px;
    font-size: 0.8125rem;
    font-weight: 500;
    white-space: nowrap;
  }

  :global(.dark) .chip {
    background: rgb(var(--stone-700));
    color: rgb(var(--stone-300));
  }

  .chip-warning {
    background: #fef3c7;
    color: #92400e;
  }

  :global(.dark) .chip-warning {
    background: #451a03;
    color: #fcd34d;
  }

  .action-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.5rem 0.875rem;
    font-size: 0.8125rem;
    font-weight: 500;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    background: rgb(var(--color-card-bg));
    color: rgb(var(--stone-700));
    cursor: pointer;
    text-decoration: none;
    transition: all 0.15s ease;
    white-space: nowrap;
  }

  :global(.dark) .action-btn {
    background: rgb(var(--stone-700));
    border-color: rgb(var(--stone-600));
    color: rgb(var(--stone-300));
  }

  .action-btn:hover {
    background: #f3f4f6;
    border-color: rgb(var(--stone-400));
  }

  :global(.dark) .action-btn:hover {
    background: rgb(var(--stone-600));
  }

  .action-btn-active {
    background: rgb(var(--color-success-light));
    border-color: rgb(var(--color-success));
    color: rgb(var(--color-success));
  }

  :global(.dark) .action-btn-active {
    background: rgb(var(--color-success-light));
    border-color: rgb(var(--color-success));
    color: rgb(var(--color-success));
  }

  .action-btn-danger {
    background: rgb(var(--color-danger-light));
    border-color: rgb(var(--color-danger));
    color: rgb(var(--color-danger));
  }

  :global(.dark) .action-btn-danger {
    background: rgb(var(--color-danger-light));
    border-color: rgb(var(--color-danger));
    color: rgb(var(--color-danger));
  }

  .action-btn-danger:hover {
    background: rgb(var(--color-danger-light));
    border-color: rgb(var(--color-danger));
  }

  .viewer-area {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .toolbar-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .player-row {
    display: flex;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .settings-row {
    animation: slideIn 0.15s ease;
  }

  @keyframes slideIn {
    from {
      opacity: 0;
      transform: translateY(-0.5rem);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .shortcut-hints {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    padding: 0.5rem 0;
    font-size: 0.75rem;
    color: rgb(var(--stone-400));
  }

  .shortcut-hints span {
    display: flex;
    align-items: center;
    gap: 0.25rem;
  }

  :global(.shortcut-hints kbd) {
    padding: 0.1rem 0.35rem;
    border: 1px solid #d1d5db;
    border-bottom-width: 2px;
    border-radius: 0.25rem;
    font-family: monospace;
    font-size: 0.7rem;
    background: #f9fafb;
    color: rgb(var(--stone-700));
  }

  .notes-section {
    padding: 1rem;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
  }

  :global(.dark) .notes-section {
    background: rgb(var(--stone-100));
    border-color: rgb(var(--stone-700));
  }

  .notes-title {
    margin: 0 0 0.5rem 0;
    font-size: 0.875rem;
    font-weight: 600;
    color: rgb(var(--stone-700));
  }

  :global(.dark) .notes-title {
    color: rgb(var(--stone-300));
  }

  .notes-content {
    margin: 0;
    font-size: 0.875rem;
    color: #6b7280;
    white-space: pre-wrap;
  }

  :global(.dark) .notes-content {
    color: #a1a1aa;
  }

  .clips-section {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    padding-top: 0.5rem;
  }

  .clip-detail-panel {
    max-width: 760px;
  }
</style>
