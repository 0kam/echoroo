<script lang="ts">
  import { page } from '$app/stores';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { getRecording, updateRecording, deleteRecording } from '$lib/api/recordings';
  import { goto } from '$app/navigation';
  import RecordingDetail from '$lib/components/data/RecordingDetail.svelte';
  import ClipCreator from '$lib/components/audio/ClipCreator.svelte';
  import ClipList from '$lib/components/data/ClipList.svelte';
  import AutoClipGenerator from '$lib/components/data/AutoClipGenerator.svelte';

  $: projectId = $page.params.id as string;
  $: recordingId = $page.params.recordingId as string;

  $: recordingQuery = createQuery({
    queryKey: ['recording', projectId, recordingId],
    queryFn: () => getRecording(projectId, recordingId),
    enabled: !!projectId && !!recordingId,
  });

  let showEditModal = false;
  let editNote = '';
  let editTimeExpansion = 1.0;
  let activeTab: 'overview' | 'clips' = 'overview';

  const queryClient = useQueryClient();

  $: updateMut = createMutation({
    mutationFn: (data: { note?: string; time_expansion?: number }) =>
      updateRecording(projectId, recordingId, data),
    onSuccess: () => {
      showEditModal = false;
      queryClient.invalidateQueries({ queryKey: ['recording', projectId, recordingId] });
    },
  });

  $: deleteMut = createMutation({
    mutationFn: () => deleteRecording(projectId, recordingId),
    onSuccess: () => {
      goto(`/projects/${projectId}/recordings`);
    },
  });

  function openEditModal() {
    if ($recordingQuery.data) {
      editNote = $recordingQuery.data.note ?? '';
      editTimeExpansion = $recordingQuery.data.time_expansion;
      showEditModal = true;
    }
  }

  function closeEditModal() {
    showEditModal = false;
  }

  function handleSubmit(event: Event) {
    event.preventDefault();
    $updateMut.mutate({ note: editNote, time_expansion: editTimeExpansion });
  }

  function handleDelete() {
    if (confirm('Are you sure you want to delete this recording? This action cannot be undone.')) {
      $deleteMut.mutate();
    }
  }
</script>

<div class="recording-page">
  {#if $recordingQuery.isLoading}
    <div class="loading-state">
      <div class="spinner"></div>
      <p>Loading recording...</p>
    </div>
  {:else if $recordingQuery.error}
    <div class="error-state">
      <svg class="error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <circle cx="12" cy="12" r="10" stroke-width="2" />
        <line x1="12" y1="8" x2="12" y2="12" stroke-width="2" />
        <line x1="12" y1="16" x2="12.01" y2="16" stroke-width="2" />
      </svg>
      <p>Error: {$recordingQuery.error.message}</p>
    </div>
  {:else if $recordingQuery.data}
    {@const recording = $recordingQuery.data}

    <!-- Breadcrumb -->
    <nav class="breadcrumb">
      <a href="/projects/{projectId}/recordings" class="breadcrumb-link">Recordings</a>
      <span class="breadcrumb-separator">/</span>
      <span class="breadcrumb-current">{recording.filename}</span>
    </nav>

    <!-- Actions -->
    <div class="action-bar">
      <button on:click={openEditModal} class="action-button action-edit">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path
            d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"
            stroke-width="2"
          />
          <path
            d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"
            stroke-width="2"
          />
        </svg>
        Edit
      </button>
      <button on:click={handleDelete} class="action-button action-delete">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <polyline points="3 6 5 6 21 6" stroke-width="2" />
          <path
            d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"
            stroke-width="2"
          />
        </svg>
        Delete
      </button>
    </div>

    <!-- Tabs -->
    <div class="tabs">
      <button
        class="tab"
        class:active={activeTab === 'overview'}
        on:click={() => (activeTab = 'overview')}
      >
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" stroke-width="2" />
          <polyline points="9 22 9 12 15 12 15 22" stroke-width="2" />
        </svg>
        Overview
      </button>
      <button
        class="tab"
        class:active={activeTab === 'clips'}
        on:click={() => (activeTab = 'clips')}
      >
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M9 11l3 3L22 4" stroke-width="2" />
          <path
            d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"
            stroke-width="2"
          />
        </svg>
        Clips
        <span class="badge">{recording.clip_count}</span>
      </button>
    </div>

    <!-- Tab content -->
    {#if activeTab === 'overview'}
      <div class="tab-content">
        <RecordingDetail {projectId} {recording} />
      </div>
    {:else if activeTab === 'clips'}
      <div class="tab-content clips-tab">
        <!-- Clip Creator -->
        <div class="section">
          <ClipCreator
            {projectId}
            {recordingId}
            duration={recording.duration}
            currentTime={0}
          />
        </div>

        <!-- Auto Clip Generator -->
        <div class="section">
          <AutoClipGenerator {projectId} {recordingId} duration={recording.duration} />
        </div>

        <!-- Clip List -->
        <div class="section">
          <ClipList {projectId} {recordingId} />
        </div>
      </div>
    {/if}
  {/if}

  <!-- Edit Modal -->
  {#if showEditModal}
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="modal-overlay" on:click={closeEditModal}>
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="modal-content" on:click|stopPropagation>
        <h3 class="modal-title">Edit Recording</h3>
        <form on:submit={handleSubmit}>
          <div class="form-fields">
            <div class="form-field">
              <label for="time-expansion" class="form-label">Time Expansion</label>
              <input
                id="time-expansion"
                type="number"
                step="0.1"
                min="0.1"
                max="100"
                bind:value={editTimeExpansion}
                class="form-input"
              />
              <p class="form-hint">Playback speed adjustment for ultrasonic recordings</p>
            </div>
            <div class="form-field">
              <label for="note" class="form-label">Notes</label>
              <textarea id="note" bind:value={editNote} rows="3" class="form-textarea"></textarea>
            </div>
          </div>
          <div class="modal-actions">
            <button type="button" on:click={closeEditModal} class="modal-button modal-cancel">
              Cancel
            </button>
            <button
              type="submit"
              class="modal-button modal-submit"
              disabled={$updateMut.isPending}
            >
              {$updateMut.isPending ? 'Saving...' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  {/if}
</div>

<style>
  .recording-page {
    padding: 2rem;
    max-width: 1600px;
    margin: 0 auto;
  }

  .loading-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 4rem;
    gap: 1rem;
  }

  .loading-state p {
    color: #6b7280;
    font-size: 0.875rem;
  }

  .spinner {
    width: 48px;
    height: 48px;
    border: 4px solid #e5e7eb;
    border-top-color: #3b82f6;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 4rem;
    gap: 1rem;
    background: #fee2e2;
    border-radius: 0.5rem;
    color: #991b1b;
  }

  .error-icon {
    width: 48px;
    height: 48px;
  }

  .breadcrumb {
    margin-bottom: 1.5rem;
    font-size: 0.875rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .breadcrumb-link {
    color: #3b82f6;
    text-decoration: none;
    transition: color 0.15s ease;
  }

  .breadcrumb-link:hover {
    color: #2563eb;
    text-decoration: underline;
  }

  .breadcrumb-separator {
    color: #9ca3af;
  }

  .breadcrumb-current {
    color: #6b7280;
  }

  .action-bar {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    margin-bottom: 2rem;
  }

  .action-button {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.625rem 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    border-radius: 0.375rem;
    border: 1px solid;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .action-button .icon {
    width: 18px;
    height: 18px;
  }

  .action-edit {
    background: white;
    color: #374151;
    border-color: #d1d5db;
  }

  .action-edit:hover {
    background: #f9fafb;
    border-color: #3b82f6;
  }

  .action-delete {
    background: #fee2e2;
    color: #991b1b;
    border-color: #fecaca;
  }

  .action-delete:hover {
    background: #fef2f2;
    border-color: #f87171;
  }

  .tabs {
    display: flex;
    gap: 0.5rem;
    border-bottom: 2px solid #e5e7eb;
    margin-bottom: 2rem;
  }

  .tab {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1.25rem;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: #6b7280;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
    margin-bottom: -2px;
  }

  .tab .icon {
    width: 18px;
    height: 18px;
  }

  .tab:hover {
    color: #374151;
    background: #f9fafb;
  }

  .tab.active {
    color: #3b82f6;
    border-bottom-color: #3b82f6;
  }

  .badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.25rem;
    height: 1.25rem;
    padding: 0 0.375rem;
    background: #e5e7eb;
    color: #374151;
    font-size: 0.75rem;
    font-weight: 600;
    border-radius: 0.75rem;
    line-height: 1;
  }

  .tab.active .badge {
    background: #dbeafe;
    color: #1e40af;
  }

  .tab-content {
    animation: fadeIn 0.2s ease;
  }

  @keyframes fadeIn {
    from {
      opacity: 0;
      transform: translateY(0.5rem);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .clips-tab {
    display: flex;
    flex-direction: column;
    gap: 2rem;
  }

  .section {
    width: 100%;
  }

  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: 1rem;
  }

  .modal-content {
    background: white;
    padding: 1.5rem;
    border-radius: 0.5rem;
    max-width: 500px;
    width: 100%;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
  }

  .modal-title {
    margin: 0 0 1.5rem 0;
    font-size: 1.25rem;
    font-weight: 600;
    color: #111827;
  }

  .form-fields {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .form-field {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .form-label {
    font-size: 0.875rem;
    font-weight: 500;
    color: #374151;
  }

  .form-input,
  .form-textarea {
    width: 100%;
    padding: 0.625rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
  }

  .form-input:focus,
  .form-textarea:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  .form-hint {
    margin: 0;
    font-size: 0.75rem;
    color: #6b7280;
  }

  .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    margin-top: 1.5rem;
  }

  .modal-button {
    padding: 0.625rem 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .modal-cancel {
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .modal-cancel:hover {
    background: #f9fafb;
  }

  .modal-submit {
    background: #3b82f6;
    color: white;
    border: 1px solid #3b82f6;
  }

  .modal-submit:hover:not(:disabled) {
    background: #2563eb;
    border-color: #2563eb;
  }

  .modal-submit:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
</style>
