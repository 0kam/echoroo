<script lang="ts">
  /**
   * RecordingDetail component - shows recording metadata.
   * The spectrogram and audio player are handled by the parent page.
   */
  import type { RecordingDetail as RecordingDetailType } from '$lib/types/data';
  import NoteEditor from '$lib/components/data/NoteEditor.svelte';
  import { getAuthenticatedRecordingDownloadUrl, updateRecording } from '$lib/api/recordings';
  import { createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    projectId: string;
    recording: RecordingDetailType;
  }

  let { projectId, recording }: Props = $props();

  const queryClient = useQueryClient();

  const noteMutation = createMutation({
    mutationFn: (note: string) =>
      updateRecording(projectId, recording.id, { note: note || null }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recording', projectId, recording.id] });
    },
  });

  function handleNoteSave(note: string) {
    $noteMutation.mutate(note);
  }

  function formatDuration(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  function formatSamplerate(sr: number): string {
    return sr >= 1000 ? `${(sr / 1000).toFixed(1)} kHz` : `${sr} Hz`;
  }

  let isDownloading = $state(false);

  async function handleDownload(event: MouseEvent) {
    // Native anchors cannot send Authorization; issue a scoped media token
    // and navigate to the tokenized BFF download URL instead.
    event.preventDefault();
    if (isDownloading) return;
    isDownloading = true;
    try {
      const url = await getAuthenticatedRecordingDownloadUrl(projectId, recording.id);
      window.location.assign(url);
    } finally {
      isDownloading = false;
    }
  }
</script>

<div class="recording-detail">
  <!-- Header -->
  <div class="flex items-start justify-between gap-4 mb-6">
    <div class="min-w-0 flex-1">
      <h2 class="text-xl font-semibold font-mono text-stone-800 break-all">
        {recording.filename}
      </h2>
      <p class="mt-1 text-sm text-stone-500 font-mono truncate">{recording.path}</p>
    </div>
    <a
      href="#download"
      download={recording.filename}
      onclick={handleDownload}
      aria-disabled={isDownloading}
      class="flex items-center gap-2 px-3 py-2 bg-success text-white rounded-md text-sm font-medium hover:opacity-90 flex-shrink-0 aria-disabled:opacity-60 aria-disabled:pointer-events-none"
    >
      <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
      {m.recording_detail_download()}
    </a>
  </div>

  <!-- Metadata grid -->
  <div class="metadata-grid mb-6">
    <div class="metadata-item">
      <span class="metadata-label">{m.recording_detail_metadata_duration()}</span>
      <p class="metadata-value">{formatDuration(recording.duration)}</p>
    </div>
    <div class="metadata-item">
      <span class="metadata-label">{m.recording_detail_metadata_effective_duration()}</span>
      <p class="metadata-value">{formatDuration(recording.effective_duration)}</p>
    </div>
    <div class="metadata-item">
      <span class="metadata-label">{m.recording_detail_metadata_sample_rate()}</span>
      <p class="metadata-value">{formatSamplerate(recording.samplerate)}</p>
    </div>
    <div class="metadata-item">
      <span class="metadata-label">{m.recording_detail_metadata_channels()}</span>
      <p class="metadata-value">{recording.channels}</p>
    </div>
    <div class="metadata-item">
      <span class="metadata-label">{m.recording_detail_metadata_bit_depth()}</span>
      <p class="metadata-value">{recording.bit_depth ?? m.recording_detail_metadata_bit_depth_na()}</p>
    </div>
    <div class="metadata-item">
      <span class="metadata-label">{m.recording_detail_metadata_time_expansion()}</span>
      <p class="metadata-value">{recording.time_expansion}x</p>
    </div>
    {#if recording.datetime}
      <div class="metadata-item">
        <span class="metadata-label">{m.recording_detail_metadata_recorded()}</span>
        <p class="metadata-value">{new Date(recording.datetime).toLocaleString(getLocale())}</p>
      </div>
      <div class="metadata-item">
        <span class="metadata-label">{m.recording_detail_metadata_datetime_status()}</span>
        <p class="metadata-value">
          <span class="status-badge status-{recording.datetime_parse_status}">
            {recording.datetime_parse_status}
          </span>
        </p>
      </div>
    {/if}
    {#if recording.dataset}
      <div class="metadata-item">
        <span class="metadata-label">{m.recording_detail_metadata_dataset()}</span>
        <p class="metadata-value">{recording.dataset.name}</p>
      </div>
    {/if}
    {#if recording.site}
      <div class="metadata-item">
        <span class="metadata-label">{m.recording_detail_metadata_site()}</span>
        <p class="metadata-value">{recording.site.name}</p>
      </div>
    {/if}
    <div class="metadata-item">
      <span class="metadata-label">{m.recording_detail_metadata_clips()}</span>
      <p class="metadata-value">{recording.clip_count}</p>
    </div>
    <div class="metadata-item">
      <span class="metadata-label">{m.recording_detail_metadata_hash()}</span>
      <p class="metadata-value font-mono text-xs break-all">{recording.hash}</p>
    </div>
    <div class="metadata-item">
      <span class="metadata-label">{m.recording_detail_metadata_created()}</span>
      <p class="metadata-value">{new Date(recording.created_at).toLocaleString(getLocale())}</p>
    </div>
    <div class="metadata-item">
      <span class="metadata-label">{m.recording_detail_metadata_updated()}</span>
      <p class="metadata-value">{new Date(recording.updated_at).toLocaleString(getLocale())}</p>
    </div>
  </div>

  <!-- Notes -->
  <div>
    <h3 class="text-sm font-semibold text-stone-700 mb-2">{m.recording_detail_notes_title()}</h3>
    <NoteEditor
      value={recording.note ?? ''}
      placeholder={m.recording_detail_notes_placeholder()}
      disabled={$noteMutation.isPending}
      onSave={handleNoteSave}
    />
    {#if $noteMutation.isError}
      <p class="mt-1 text-xs text-danger">
        {m.recording_detail_notes_save_error({ message: $noteMutation.error?.message ?? '' })}
      </p>
    {/if}
  </div>
</div>

<style>
  .metadata-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 1.25rem;
  }

  .metadata-item {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .metadata-label {
    font-size: 0.6875rem;
    font-weight: 500;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .metadata-value {
    margin: 0;
    font-size: 0.875rem;
    font-weight: 500;
    color: #111827;
  }

  :global(.dark) .metadata-value {
    color: #f3f4f6;
  }

  .status-badge {
    display: inline-block;
    padding: 0.2rem 0.5rem;
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
