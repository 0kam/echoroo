<script lang="ts">
  // Test fixture route — for E2E testing only. DO NOT use in production.

  import SpectrogramViewer from '$lib/components/audio/SpectrogramViewer.svelte';
  import {
    DEFAULT_SPECTROGRAM_SETTINGS,
    type SpectrogramWindow,
    type InteractionMode,
  } from '$lib/types/audio';
  import type { RecordingDetail } from '$lib/types/data';

  // test1 project — 30-minute recording used for E2E tests.
  const TEST_PROJECT_ID = '6ed4e592-87ca-4fa7-a384-c64ca6bfeec5';

  // Hardcoded recording stub — avoids a network round-trip and eliminates the
  // flaky "empty content" failure caused by API latency after previous test load.
  // The spectrogram viewer only needs samplerate, duration, id, and dataset_id
  // to render; the remaining fields are set to safe defaults.
  const STUB_RECORDING: RecordingDetail = {
    id: 'c05a228d-61df-4a89-bd84-6620143c4eaf',
    dataset_id: 'fixture-dataset',
    filename: 'fixture.wav',
    path: 'recordings/fixture/fixture.wav',
    hash: 'fixture',
    duration: 1800,
    samplerate: 48000,
    channels: 1,
    bit_depth: 16,
    datetime: null,
    datetime_parse_status: 'pending',
    datetime_parse_error: null,
    time_expansion: 1,
    note: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    dataset: null,
    site: null,
    clip_count: 0,
    effective_duration: 1800,
    is_ultrasonic: false,
  };

  const projectId = TEST_PROJECT_ID;

  // Fixed viewport and bounds — intentionally not updated by interactions.
  let viewport = $state<SpectrogramWindow>({
    time: { min: 0, max: 20 },
    freq: { min: 0, max: 24000 },
  });

  let bounds = $state<SpectrogramWindow>({
    time: { min: 0, max: 1800 },
    freq: { min: 0, max: 24000 },
  });

  const interactionMode: InteractionMode = 'panning';
  const currentTime = 0;

  // Callback fire counters — exposed via data attributes for Playwright assertions.
  let changeCount = $state(0);
  let saveCount = $state(0);
  let seekCount = $state(0);
  let modeChangeCount = $state(0);

  function handleViewportChange(v: SpectrogramWindow) {
    changeCount += 1;
    // readonly=true prevents this from being called; log for debugging if it is.
    void v;
  }

  function handleViewportSave() {
    saveCount += 1;
  }

  function handleSeek(time: number) {
    seekCount += 1;
    void time;
  }

  function handleModeChange(mode: InteractionMode) {
    modeChangeCount += 1;
    void mode;
  }
</script>

<div class="p-4">
  <h1 class="mb-4 text-sm font-semibold text-stone-600">
    SpectrogramViewer fixture — readonly=true
  </h1>

  <!-- Callback counters exposed for Playwright -->
  <div
    data-testid="callback-count"
    data-change={changeCount}
    data-save={saveCount}
    data-seek={seekCount}
    data-mode-change={modeChangeCount}
  ></div>

  <SpectrogramViewer
    recording={STUB_RECORDING}
    {projectId}
    spectrogramSettings={DEFAULT_SPECTROGRAM_SETTINGS}
    {viewport}
    {bounds}
    {currentTime}
    {interactionMode}
    readonly={true}
    onViewportChange={handleViewportChange}
    onViewportSave={handleViewportSave}
    onSeek={handleSeek}
    onModeChange={handleModeChange}
  />
</div>
