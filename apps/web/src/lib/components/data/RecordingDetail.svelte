<script lang="ts">
  import type { RecordingDetail, SpectrogramParams } from '$lib/types/data';
  import SpectrogramViewer from '$lib/components/audio/SpectrogramViewer.svelte';
  import AudioPlayer from '$lib/components/audio/AudioPlayer.svelte';
  import PlaybackSpeedControl from '$lib/components/audio/PlaybackSpeedControl.svelte';
  import NoteEditor from '$lib/components/data/NoteEditor.svelte';
  import SpectrogramSettings from '$lib/components/audio/SpectrogramSettings.svelte';
  import DownloadButton from '$lib/components/data/DownloadButton.svelte';
  import { getDownloadUrl, updateRecording } from '$lib/api/recordings';
  import { createMutation, useQueryClient } from '@tanstack/svelte-query';

  export let projectId: string;
  export let recording: RecordingDetail;

  const queryClient = useQueryClient();

  let currentTime = 0;
  let playbackSpeed = recording.is_ultrasonic ? recording.time_expansion || 10.0 : 1.0;
  let audioPlayer: AudioPlayer;
  let showSpectrogramSettings = false;
  let spectrogramParams: SpectrogramParams = {};

  // Note update mutation
  const noteMutation = createMutation({
    mutationFn: (note: string) =>
      updateRecording(projectId, recording.id, { note: note || null }),
    onSuccess: (updatedRecording) => {
      recording = { ...recording, note: updatedRecording.note };
      queryClient.invalidateQueries({ queryKey: ['recordings', projectId, recording.id] });
    },
  });

  function handleTimeClick(time: number) {
    audioPlayer?.seek(time);
  }

  function formatDuration(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  function formatSamplerate(sr: number): string {
    return sr >= 1000 ? `${(sr / 1000).toFixed(1)} kHz` : `${sr} Hz`;
  }

  function formatFilesize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function handleSpeedChange(newSpeed: number) {
    playbackSpeed = newSpeed;
  }

  function handleNoteSave(event: CustomEvent<string>) {
    $noteMutation.mutate(event.detail);
  }

  function handleSpectrogramSettingsChange(params: SpectrogramParams) {
    spectrogramParams = params;
  }

  function toggleSpectrogramSettings() {
    showSpectrogramSettings = !showSpectrogramSettings;
  }
</script>

<div class="recording-detail">
  <!-- Header -->
  <div class="header">
    <div class="title-section">
      <h2 class="filename">{recording.filename}</h2>
      <p class="filepath">{recording.path}</p>
    </div>
    <DownloadButton
      url={getDownloadUrl(projectId, recording.id)}
      filename={recording.filename}
      label="Download"
      variant="primary"
    />
  </div>

  <!-- Spectrogram -->
  <div class="section">
    <div class="section-header">
      <h3 class="section-title">Spectrogram</h3>
      <button type="button" class="settings-toggle" onclick={toggleSpectrogramSettings}>
        <svg class="settings-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <circle cx="12" cy="12" r="3" stroke-width="2" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" stroke-width="2" />
        </svg>
        Settings
      </button>
    </div>
    {#if showSpectrogramSettings}
      <div class="settings-panel">
        <SpectrogramSettings
          params={spectrogramParams}
          onChange={handleSpectrogramSettingsChange}
          samplerate={recording.samplerate}
        />
      </div>
    {/if}
    <SpectrogramViewer
      {projectId}
      recordingId={recording.id}
      duration={recording.duration}
      params={spectrogramParams}
      onTimeClick={handleTimeClick}
    />
  </div>

  <!-- Playback controls -->
  <div class="section">
    <h3 class="section-title">Playback</h3>
    <div class="playback-controls">
      <div class="player-wrapper">
        <AudioPlayer
          bind:this={audioPlayer}
          {projectId}
          recordingId={recording.id}
          duration={recording.duration}
          speed={playbackSpeed}
          isUltrasonic={recording.is_ultrasonic}
          bind:currentTime
        />
      </div>
      <PlaybackSpeedControl
        speed={playbackSpeed}
        isUltrasonic={recording.is_ultrasonic}
        onChange={handleSpeedChange}
      />
    </div>
  </div>

  <!-- Metadata -->
  <div class="section">
    <h3 class="section-title">Recording Information</h3>
    <div class="metadata-grid">
      <div class="metadata-item">
        <span class="metadata-label">Duration</span>
        <p class="metadata-value">{formatDuration(recording.duration)}</p>
      </div>
      <div class="metadata-item">
        <span class="metadata-label">Effective Duration</span>
        <p class="metadata-value">{formatDuration(recording.effective_duration)}</p>
      </div>
      <div class="metadata-item">
        <span class="metadata-label">Sample Rate</span>
        <p class="metadata-value">{formatSamplerate(recording.samplerate)}</p>
      </div>
      <div class="metadata-item">
        <span class="metadata-label">Channels</span>
        <p class="metadata-value">{recording.channels}</p>
      </div>
      <div class="metadata-item">
        <span class="metadata-label">Bit Depth</span>
        <p class="metadata-value">{recording.bit_depth ?? 'N/A'}</p>
      </div>
      <div class="metadata-item">
        <span class="metadata-label">Time Expansion</span>
        <p class="metadata-value">{recording.time_expansion}x</p>
      </div>
      {#if recording.datetime}
        <div class="metadata-item">
          <span class="metadata-label">Recorded</span>
          <p class="metadata-value">{new Date(recording.datetime).toLocaleString()}</p>
        </div>
        <div class="metadata-item">
          <span class="metadata-label">DateTime Status</span>
          <p class="metadata-value">
            <span
              class="status-badge"
              class:status-success={recording.datetime_parse_status === 'success'}
              class:status-pending={recording.datetime_parse_status === 'pending'}
              class:status-failed={recording.datetime_parse_status === 'failed'}
            >
              {recording.datetime_parse_status}
            </span>
          </p>
        </div>
      {/if}
      {#if recording.dataset}
        <div class="metadata-item">
          <span class="metadata-label">Dataset</span>
          <p class="metadata-value">{recording.dataset.name}</p>
        </div>
      {/if}
      {#if recording.site}
        <div class="metadata-item">
          <span class="metadata-label">Site</span>
          <p class="metadata-value">{recording.site.name}</p>
        </div>
      {/if}
      <div class="metadata-item">
        <span class="metadata-label">Clips</span>
        <p class="metadata-value">{recording.clip_count}</p>
      </div>
      <div class="metadata-item">
        <span class="metadata-label">Hash</span>
        <p class="metadata-value hash">{recording.hash}</p>
      </div>
      <div class="metadata-item">
        <span class="metadata-label">Created</span>
        <p class="metadata-value">{new Date(recording.created_at).toLocaleString()}</p>
      </div>
      <div class="metadata-item">
        <span class="metadata-label">Updated</span>
        <p class="metadata-value">{new Date(recording.updated_at).toLocaleString()}</p>
      </div>
    </div>
  </div>

  <!-- Notes -->
  <div class="section">
    <h3 class="section-title">Notes</h3>
    <NoteEditor
      value={recording.note ?? ''}
      placeholder="Add notes about this recording..."
      disabled={$noteMutation.isPending}
      on:save={handleNoteSave}
    />
    {#if $noteMutation.isError}
      <p class="error-text">Failed to save note: {$noteMutation.error?.message}</p>
    {/if}
  </div>
</div>

<style>
  .recording-detail {
    width: 100%;
    max-width: 1400px;
    margin: 0 auto;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 2rem;
    gap: 1rem;
  }

  .title-section {
    flex: 1;
    min-width: 0;
  }

  .filename {
    margin: 0;
    font-size: 1.5rem;
    font-weight: 600;
    color: #111827;
    font-family: monospace;
    word-break: break-all;
  }

  .filepath {
    margin: 0.5rem 0 0;
    font-size: 0.875rem;
    color: #6b7280;
    font-family: monospace;
  }

  .section {
    margin-bottom: 2rem;
  }

  .section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
  }

  .section-header .section-title {
    margin: 0;
  }

  .section-title {
    margin: 0 0 1rem 0;
    font-size: 1.125rem;
    font-weight: 600;
    color: #111827;
  }

  .settings-toggle {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.5rem 0.75rem;
    background: white;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.813rem;
    font-weight: 500;
    color: #374151;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .settings-toggle:hover {
    background: #f9fafb;
    border-color: #9ca3af;
  }

  .settings-icon {
    width: 16px;
    height: 16px;
  }

  .settings-panel {
    margin-bottom: 1rem;
  }

  .error-text {
    margin: 0.5rem 0 0;
    font-size: 0.813rem;
    color: #dc2626;
  }

  .playback-controls {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .player-wrapper {
    width: 100%;
  }

  .metadata-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 1.5rem;
  }

  .metadata-item {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .metadata-label {
    font-size: 0.75rem;
    font-weight: 500;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .metadata-value {
    margin: 0;
    font-size: 0.875rem;
    font-weight: 500;
    color: #111827;
  }

  .metadata-value.hash {
    font-family: monospace;
    font-size: 0.75rem;
    word-break: break-all;
  }

  .status-badge {
    display: inline-block;
    padding: 0.25rem 0.625rem;
    border-radius: 0.25rem;
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: capitalize;
  }

  .status-success {
    background: #d1fae5;
    color: #065f46;
  }

  .status-pending {
    background: #fef3c7;
    color: #92400e;
  }

  .status-failed {
    background: #fee2e2;
    color: #991b1b;
  }
</style>
