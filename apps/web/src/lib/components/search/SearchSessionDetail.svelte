<script lang="ts">
  /**
   * SearchSessionDetail - Full detail view for a persisted search session.
   *
   * Displays the session header (name, date, status, result count, duration),
   * the reconstructed reference audio in readonly mode, a re-run button, and
   * the full results panel.
   */

  import * as m from '$lib/paraglide/messages';
  import { getLocale, localizeHref } from '$lib/paraglide/runtime';
  import { getSearchSession, getReferenceAudioUrl, updateSearchSession, exportSearchSessionRecordingsCSV } from '$lib/api/search';
  import { fetchCustomModels } from '$lib/api/custom-models';
  import { generateId } from '$lib/utils/id';
  import type { SearchSession, TargetSpecies, SoundSource } from '$lib/types/search';
  import type { CustomModelListItem } from '$lib/types/custom-model';
  import ReferenceSoundsPanel from './ReferenceSoundsPanel.svelte';
  import ResultsPanel from './ResultsPanel.svelte';
  import CreateModelFromSessionDialog from './CreateModelFromSessionDialog.svelte';
  import ReviewTab from '$lib/components/models/ReviewTab.svelte';
  import {
    getSearchSessionStatusLabel,
    getSearchSessionStatusTextClass,
    getSearchSessionStatusDetailDotClass,
  } from '$lib/utils/statusFormatters';

  interface Props {
    projectId: string;
    sessionId: string;
    onBack: () => void;
    onRerun: (species: TargetSpecies[], editingSessionId: string | null, datasetId?: string) => void;
  }

  let { projectId, sessionId, onBack, onRerun }: Props = $props();

  // ============================================
  // State
  // ============================================

  let session = $state<SearchSession | null>(null);
  let isLoading = $state(true);
  let loadError = $state<string | null>(null);

  // Reconstructed TargetSpecies for the ReferenceSoundsPanel
  let reconstructedSpecies = $state<TargetSpecies[]>([]);

  // Currently selected species key (tracked from ResultsPanel)
  let currentSpeciesKey = $state<string | null>(null);

  // ============================================
  // Model Training section state
  // ============================================

  /** Custom models linked to this session */
  let sessionModels = $state<CustomModelListItem[]>([]);
  let isLoadingModels = $state(false);
  let modelsLoadError = $state<string | null>(null);

  /** Which species' "Train Model" dialog is open (by index in species_config) */
  let trainDialogSpeciesIndex = $state<number | null>(null);

  async function loadSessionModels(pid: string, sid: string) {
    isLoadingModels = true;
    modelsLoadError = null;
    try {
      const res = await fetchCustomModels(pid, { search_session_id: sid });
      sessionModels = res.models;
    } catch (e) {
      modelsLoadError = e instanceof Error ? e.message : 'Failed to load models';
    } finally {
      isLoadingModels = false;
    }
  }

  function handleTrainModelForSpecies(index: number) {
    trainDialogSpeciesIndex = index;
  }

  function handleCreateModelSuccess(_modelId: string) {
    trainDialogSpeciesIndex = null;
    // Reload models list so the new model appears in the training section
    if (session) {
      loadSessionModels(projectId, session.id);
    }
  }

  // Recordings CSV export state
  let isExportingRecordings = $state(false);

  async function handleExportRecordings() {
    if (!session) return;
    isExportingRecordings = true;
    try {
      await exportSearchSessionRecordingsCSV(projectId, session.id, getLocale());
    } catch (e) {
      console.error('Recordings export failed:', e);
    } finally {
      isExportingRecordings = false;
    }
  }

  // Dataset name (resolved from session.parameters.dataset_id)
  let datasetName = $state<string | null>(null);

  // Inline rename state
  let isRenaming = $state(false);
  let renameValue = $state('');
  let isSavingRename = $state(false);
  let renameError = $state<string | null>(null);
  let renameInputEl = $state<HTMLInputElement | null>(null);

  // ============================================
  // Data fetching
  // ============================================

  async function loadSession(pid: string, sid: string) {
    isLoading = true;
    loadError = null;
    session = null;
    reconstructedSpecies = [];

    try {
      const data = await getSearchSession(pid, sid, getLocale());
      session = data;

      // Resolve dataset name from parameters.dataset_id
      datasetName = null;
      if (data.parameters?.dataset_id) {
        try {
          const { fetchDataset } = await import('$lib/api/datasets');
          const ds = await fetchDataset(pid, data.parameters.dataset_id);
          datasetName = ds.name ?? null;
        } catch {
          // Non-critical — just skip dataset name display
        }
      }

      // Reconstruct reference audio sources from persisted session data
      if (data.species_config) {
        const loaded: TargetSpecies[] = [];

        for (const spConfig of data.species_config) {
          const speciesSources = (spConfig.sources ?? []).reduce<SoundSource[]>((acc, srcConfig) => {
            const src = srcConfig as Record<string, unknown>;
            const s3Key = src['s3_key'] as string | undefined;
            const sourceUrl = src['source_url'] as string | undefined;
            const xcId = src['xc_id'] as string | undefined;

            if (s3Key && data.reference_audio_keys) {
              // S3-persisted source (uploaded files)
              const keyIndex = data.reference_audio_keys.indexOf(s3Key);
              if (keyIndex >= 0) {
                const fileKey = src['file_key'] as string | undefined;
                acc.push({
                  id: generateId(),
                  origin: 's3' as const,
                  label: fileKey ?? `Source ${keyIndex + 1}`,
                  streamUrl: getReferenceAudioUrl(pid, sid, keyIndex),
                  sourceIndex: keyIndex,
                  start_time: src['start_time'] as number | undefined,
                  end_time: src['end_time'] as number | undefined,
                });
              }
            } else if (sourceUrl || xcId) {
              // URL-based source (Xeno-Canto)
              // Extract XC ID from URL if not explicitly provided
              let resolvedXcId = xcId as string | undefined;
              if (!resolvedXcId && sourceUrl) {
                const xcMatch = sourceUrl.match(/xeno-canto\.org\/(\d+)/);
                if (xcMatch) resolvedXcId = xcMatch[1];
              }
              acc.push({
                id: generateId(),
                origin: 'url' as const,
                label: resolvedXcId ? `XC${resolvedXcId}` : (sourceUrl ?? 'URL source'),
                source_url: sourceUrl,
                xc_id: resolvedXcId,
                start_time: src['start_time'] as number | undefined,
                end_time: src['end_time'] as number | undefined,
              });
            }
            return acc;
          }, []);

          // Include species even if no sources could be reconstructed
          loaded.push({
            id: generateId(),
            tag_id: spConfig.tag_id,
            scientific_name: spConfig.scientific_name,
            common_name: spConfig.common_name ?? undefined,
            sources: speciesSources,
          });
        }

        reconstructedSpecies = loaded;
      }
    } catch (e) {
      loadError = e instanceof Error ? e.message : m.search_error_search_failed();
    } finally {
      isLoading = false;
    }
  }

  // Load session on mount and reload when sessionId changes
  $effect(() => {
    loadSession(projectId, sessionId);
    loadSessionModels(projectId, sessionId);
  });

  // ============================================
  // Derived
  // ============================================

  const statusLabel = $derived(() => {
    if (!session) return '';
    return getSearchSessionStatusLabel(session.status, {
      completed: m.search_session_status_completed,
      running: m.search_session_status_running,
      failed: m.search_session_status_failed,
      pending: m.search_session_status_pending,
    });
  });

  const statusColor = $derived(() => {
    if (!session) return 'text-stone-500';
    return getSearchSessionStatusTextClass(session.status);
  });

  const statusDotColor = $derived(() => {
    if (!session) return 'bg-stone-400';
    return getSearchSessionStatusDetailDotClass(session.status);
  });

  const sessionName = $derived(() => {
    if (!session) return '';
    if (session.name) return session.name;
    if (session.species_config && session.species_config.length > 0) {
      return session.species_config
        .map((sp) => {
          if (sp.common_name && sp.common_name !== sp.scientific_name) {
            return `${sp.common_name} (${sp.scientific_name})`;
          }
          return sp.scientific_name;
        })
        .join(', ');
    }
    return m.search_session_detail();
  });

  const formattedDate = $derived(() => {
    if (!session) return '';
    const dateStr = session.completed_at ?? session.started_at ?? session.created_at;
    try {
      return new Date(dateStr).toLocaleString();
    } catch {
      return dateStr;
    }
  });

  const searchDuration = $derived(() => {
    if (!session?.results) return 0;
    return session.results.search_duration_ms;
  });

  // ============================================
  // Rename handlers
  // ============================================

  function startRename() {
    if (!session) return;
    renameValue = session.name ?? sessionName();
    renameError = null;
    isRenaming = true;
    // Focus the input on the next tick after it renders
    setTimeout(() => renameInputEl?.focus(), 0);
  }

  function cancelRename() {
    isRenaming = false;
    renameError = null;
  }

  async function saveRename() {
    if (!session || !renameValue.trim()) return;
    isSavingRename = true;
    renameError = null;
    try {
      const updated = await updateSearchSession(projectId, session.id, renameValue.trim());
      session = updated;
      isRenaming = false;
    } catch (e) {
      renameError = e instanceof Error ? e.message : m.search_error_search_failed();
    } finally {
      isSavingRename = false;
    }
  }

  function handleRenameKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      saveRename();
    } else if (e.key === 'Escape') {
      cancelRename();
    }
  }

  // ============================================
  // Edit & Re-search handler (updates existing session in-place)
  // ============================================

  function handleEditRerun() {
    if (reconstructedSpecies.length === 0 || !session) return;

    // Deep-clone so edits in new-search mode don't affect this detail view
    const cloned: TargetSpecies[] = reconstructedSpecies.map((sp) => ({
      ...sp,
      id: generateId(),
      sources: sp.sources.map((src) => ({ ...src, id: generateId() })),
    }));

    // Pass the session ID and dataset_id so the parent restores the correct config
    onRerun(cloned, session.id, session.parameters?.dataset_id ?? undefined);
  }

  // ============================================
  // Fork handler (creates a brand-new session)
  // ============================================

  function handleFork() {
    if (reconstructedSpecies.length === 0) return;

    // Deep-clone — pass null session ID to signal "create new"
    const cloned: TargetSpecies[] = reconstructedSpecies.map((sp) => ({
      ...sp,
      id: generateId(),
      sources: sp.sources.map((src) => ({ ...src, id: generateId() })),
    }));

    onRerun(cloned, null, session?.parameters?.dataset_id ?? undefined);
  }
</script>

<div class="space-y-6">
  <!-- Back navigation -->
  <div>
    <button
      type="button"
      class="inline-flex items-center gap-1.5 text-sm text-stone-500 transition-colors hover:text-stone-900 dark:hover:text-stone-100"
      onclick={onBack}
    >
      <!-- Left arrow icon -->
      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M19 12H5M12 19l-7-7 7-7" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      {m.search_back_to_sessions()}
    </button>
  </div>

  {#if isLoading}
    <!-- Loading skeleton -->
    <div class="space-y-4">
      <!-- Header skeleton -->
      <div class="rounded-lg border border-stone-200 bg-surface-card p-6 shadow-sm dark:border-stone-700">
        <div class="mb-2 h-6 w-2/5 animate-pulse rounded bg-stone-200 dark:bg-stone-700"></div>
        <div class="h-4 w-1/3 animate-pulse rounded bg-stone-100 dark:bg-stone-800"></div>
      </div>
      <!-- Reference audio skeleton -->
      <div class="rounded-lg border border-stone-200 bg-surface-card p-6 shadow-sm dark:border-stone-700">
        <div class="mb-4 h-5 w-1/4 animate-pulse rounded bg-stone-200 dark:bg-stone-700"></div>
        <div class="h-20 animate-pulse rounded bg-stone-100 dark:bg-stone-800"></div>
      </div>
      <!-- Results skeleton -->
      <div class="rounded-lg border border-stone-200 bg-surface-card p-6 shadow-sm dark:border-stone-700">
        <div class="mb-4 h-5 w-1/4 animate-pulse rounded bg-stone-200 dark:bg-stone-700"></div>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {#each { length: 8 } as _}
            <div class="animate-pulse overflow-hidden rounded-lg border border-stone-200 bg-surface-card shadow-sm dark:border-stone-700">
              <div class="h-[120px] bg-stone-200 dark:bg-stone-700"></div>
              <div class="flex flex-col gap-2 p-2.5">
                <div class="h-3 w-4/5 rounded bg-stone-100 dark:bg-stone-800"></div>
                <div class="h-3 w-1/2 rounded bg-stone-100 dark:bg-stone-800"></div>
              </div>
            </div>
          {/each}
        </div>
      </div>
    </div>

  {:else if loadError}
    <!-- Error state -->
    <div class="rounded-lg border border-danger/30 bg-danger-light p-4 text-sm text-danger">
      {loadError}
    </div>

  {:else if session}
    <!-- Session header card -->
    <div class="rounded-lg border border-stone-200 bg-surface-card p-5 shadow-sm dark:border-stone-700">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0 flex-1">
          <!-- Session name with inline rename -->
          {#if isRenaming}
            <div class="flex items-center gap-2">
              <input
                bind:this={renameInputEl}
                bind:value={renameValue}
                type="text"
                aria-label={m.search_session_name()}
                class="min-w-0 flex-1 rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-lg font-semibold text-stone-900
                       shadow-sm outline-none ring-primary-500 focus:border-primary-500 focus:ring-2
                       dark:border-stone-600"
                disabled={isSavingRename}
                onkeydown={handleRenameKeydown}
              />
              <button
                type="button"
                class="shrink-0 rounded-md bg-primary-600 px-3 py-1.5 text-sm font-medium text-white
                       transition-colors hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2
                       disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
                disabled={isSavingRename || !renameValue.trim()}
                onclick={saveRename}
              >
                {isSavingRename ? m.search_rename_saving() : m.search_rename_save()}
              </button>
              <button
                type="button"
                class="shrink-0 rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm font-medium
                       text-stone-700 transition-colors hover:bg-stone-50 dark:hover:bg-stone-700 disabled:opacity-50
                       dark:border-stone-600"
                disabled={isSavingRename}
                onclick={cancelRename}
              >
                {m.search_rename_cancel()}
              </button>
            </div>
            {#if renameError}
              <p class="mt-1 text-sm text-danger">{renameError}</p>
            {/if}
          {:else}
            <div class="flex items-center gap-2">
              <h2 class="truncate text-xl font-semibold text-stone-900">
                {sessionName()}
              </h2>
              {#if session.status === 'completed'}
                <button
                  type="button"
                  title={m.search_rename_session()}
                  aria-label={m.search_rename_session()}
                  class="shrink-0 rounded p-1 text-stone-400 transition-colors hover:text-stone-700
                         dark:hover:text-stone-300"
                  onclick={startRename}
                >
                  <!-- Pencil icon -->
                  <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" stroke-linecap="round" stroke-linejoin="round" />
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" stroke-linecap="round" stroke-linejoin="round" />
                  </svg>
                </button>
              {/if}
            </div>
          {/if}
          <p class="mt-0.5 text-sm text-stone-500">
            {formattedDate()}
          </p>

          <!-- Status + meta row -->
          <div class="mt-2 flex flex-wrap items-center gap-3 text-sm">
            <!-- Status badge -->
            <span class="inline-flex items-center gap-1.5 font-medium {statusColor()}">
              <span class="inline-block h-2 w-2 rounded-full {statusDotColor()}"></span>
              {statusLabel()}
            </span>

            {#if datasetName}
              <span class="text-stone-400">·</span>
              <span class="text-stone-500">{datasetName}</span>
            {/if}

            {#if session.model_name}
              <span class="text-stone-400">·</span>
              <span class="rounded bg-stone-100 px-1.5 py-0.5 text-xs font-medium text-stone-600 dark:bg-stone-700 dark:text-stone-300">{session.model_name}</span>
            {/if}

            {#if searchDuration() > 0}
              <span class="text-stone-400">·</span>
              <span class="text-stone-500">
                {m.search_search_duration({ ms: String(searchDuration()) })}
              </span>
            {/if}
          </div>
        </div>

        <!-- Export button -->
        {#if session.status === 'completed' && session.result_count > 0}
          <div class="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onclick={handleExportRecordings}
              disabled={isExportingRecordings}
              class="inline-flex items-center gap-1.5 rounded-lg border border-stone-300 bg-surface-card px-3 py-1.5 text-sm font-medium text-stone-700 shadow-sm transition hover:bg-stone-50 disabled:opacity-50"
            >
              {#if isExportingRecordings}
                <svg class="h-4 w-4 animate-spin text-stone-400" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                Exporting...
              {:else}
                <svg class="h-4 w-4 text-stone-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                </svg>
                {m.search_export_csv()}
              {/if}
            </button>
          </div>
        {/if}
      </div>

      <!-- Error message for failed sessions -->
      {#if session.status === 'failed' && session.error_message}
        <div class="mt-3 rounded-md border border-danger/30 bg-danger-light px-3 py-2 text-sm text-danger">
          {session.error_message}
        </div>
      {/if}
    </div>

    <!-- Reference audio section -->
    {#if reconstructedSpecies.length > 0}
      <ReferenceSoundsPanel
        {projectId}
        species={reconstructedSpecies}
        modelName={session.model_name}
        onSpeciesChange={() => {}}
        readonly={true}
      />
    {/if}

    <!-- Action buttons (for completed sessions) -->
    {#if session.status === 'completed' && reconstructedSpecies.length > 0}
      <div class="flex items-center justify-end gap-2">
        <!-- Fork: create a brand-new session preserving old results -->
        <button
          type="button"
          class="inline-flex items-center gap-2 rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium
                 text-stone-500 shadow-sm transition-colors hover:bg-stone-50 hover:text-stone-700
                 dark:border-stone-600 dark:hover:bg-stone-700 dark:hover:text-stone-300"
          onclick={handleFork}
        >
          <!-- Fork icon (git-branch) -->
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="18" cy="18" r="3" stroke-linecap="round" stroke-linejoin="round" />
            <circle cx="6" cy="6" r="3" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M13 6h3a2 2 0 0 1 2 2v7M6 9v12" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          {m.search_fork_session()}
        </button>

        <!-- Edit & Re-search: update existing session in-place -->
        <button
          type="button"
          class="inline-flex items-center gap-2 rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium
                 text-stone-700 shadow-sm transition-colors hover:bg-stone-50
                 dark:border-stone-600 dark:hover:bg-stone-700"
          onclick={handleEditRerun}
        >
          <!-- Edit icon -->
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          {m.search_edit_rerun()}
        </button>
      </div>
    {/if}

    <!-- Results section -->
    {#if session.status === 'completed' && session.results}
      <ResultsPanel
        {projectId}
        sessionId={session.id}
        results={session.results.results}
        searchDurationMs={searchDuration()}
        isSearching={false}
        searchingSpecies={reconstructedSpecies}
        onSpeciesKeyChange={(key) => { currentSpeciesKey = key; }}
      />
    {:else if session.status === 'failed'}
      <!-- Failed state - no results -->
      <div class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-stone-200 py-12 text-center dark:border-stone-700">
        <svg
          class="mx-auto mb-3 h-10 w-10 text-danger/50 dark:text-danger"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="1.5"
          aria-hidden="true"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
        </svg>
        <p class="font-medium text-stone-500">{m.search_session_status_failed()}</p>
      </div>
    {:else if session.status === 'pending' || session.status === 'running'}
      <!-- Pending/running state -->
      <div class="flex items-center justify-center gap-3 rounded-lg border border-stone-200 bg-surface-card p-6 text-sm text-stone-600 dark:border-stone-700">
        <svg class="h-5 w-5 animate-spin text-primary-500" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        <span>{m.search_session_status_running()}</span>
      </div>
    {:else if session.status === 'completed' && !session.results}
      <!-- Completed but no results -->
      <div class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-stone-200 py-12 text-center dark:border-stone-700">
        <svg
          class="mx-auto mb-3 h-10 w-10 text-stone-300"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="1.5"
          aria-hidden="true"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
        </svg>
        <p class="font-medium text-stone-500">{m.search_results_no_matches()}</p>
        <p class="mt-1 text-sm text-stone-400">{m.search_results_no_matches_hint()}</p>
      </div>
    {/if}

    <!-- ============================================
         Model Training section
         Only shown for completed sessions with results.
    ============================================ -->
    {#if session.status === 'completed' && session.result_count > 0 && session.species_config && session.species_config.length > 0}
      <div class="rounded-lg border border-stone-200 bg-surface-card p-5 shadow-sm dark:border-stone-700">
        <h3 class="mb-4 text-base font-semibold text-stone-800 dark:text-stone-200">
          Model Training
        </h3>

        {#if isLoadingModels}
          <div class="flex items-center gap-2 text-sm text-stone-400">
            <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            Loading models...
          </div>
        {:else if modelsLoadError}
          <p class="text-sm text-danger">{modelsLoadError}</p>
        {:else}
          <div class="space-y-4">
            {#each session.species_config as spConfig, idx (spConfig.scientific_name)}
              {@const linkedModel = sessionModels.find(
                (mdl) => mdl.target_tag_id === spConfig.tag_id
              ) ?? sessionModels[0] ?? null}

              <div class="rounded-lg border border-stone-100 p-4 dark:border-stone-800">
                <!-- Species header -->
                <div class="mb-3 flex items-center gap-2">
                  <p class="text-sm font-medium italic text-stone-800 dark:text-stone-200">
                    {spConfig.scientific_name}
                  </p>
                  {#if spConfig.common_name && spConfig.common_name !== spConfig.scientific_name}
                    <span class="text-xs text-stone-400">({spConfig.common_name})</span>
                  {/if}
                </div>

                {#if !linkedModel}
                  <!-- No model yet — show Train Model button -->
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white
                           shadow-sm transition-colors hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2
                           dark:bg-primary-500 dark:hover:bg-primary-400"
                    onclick={() => handleTrainModelForSpecies(idx)}
                  >
                    <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.347a3.001 3.001 0 01-.468 3.525L12 20.5l-2.626-2.626a3.001 3.001 0 01-.468-3.525l-.347-.347z" />
                    </svg>
                    Train Model
                  </button>

                {:else if linkedModel.status === 'draft'}
                  <!-- Draft model — show ReviewTab for labeling -->
                  <div class="mb-2 flex items-center gap-2">
                    <span class="inline-flex items-center rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-xs font-medium text-stone-600 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-400">
                      {linkedModel.status}
                    </span>
                    <span class="text-xs text-stone-500">{linkedModel.name}</span>
                  </div>

                  <!-- Show ReviewTab for labeling seed samples -->
                  <div class="mt-3 rounded-lg border border-stone-100 dark:border-stone-800 overflow-hidden">
                    <ReviewTab
                      {projectId}
                      modelId={linkedModel.id}
                      onTrainRequest={() => {}}
                    />
                  </div>

                {:else if linkedModel.status === 'training'}
                  <!-- Training in progress -->
                  <div class="flex items-center gap-2 text-sm text-stone-600 dark:text-stone-400">
                    <svg class="h-4 w-4 animate-spin text-primary-500" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                    </svg>
                    Training in progress...
                    <span class="text-xs text-stone-400">({linkedModel.name})</span>
                  </div>

                {:else if linkedModel.status === 'trained' || linkedModel.status === 'deployed'}
                  <!-- Trained model — show summary + navigation links -->
                  <div class="space-y-2">
                    <div class="flex items-center gap-2">
                      <span class="inline-flex items-center rounded-full border border-success/30 bg-success-light px-2 py-0.5 text-xs font-medium text-success">
                        {linkedModel.status}
                      </span>
                      <span class="text-xs text-stone-500">{linkedModel.name}</span>
                    </div>
                    <div class="flex flex-wrap items-center gap-2">
                      <a
                        href={localizeHref(`/projects/${projectId}/models`)}
                        class="inline-flex items-center gap-1.5 rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-xs font-medium
                               text-stone-600 transition-colors hover:bg-stone-50 dark:border-stone-600 dark:hover:bg-stone-700"
                      >
                        View in Models
                        <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                        </svg>
                      </a>
                    </div>
                  </div>

                {:else if linkedModel.status === 'failed'}
                  <!-- Failed model -->
                  <div class="space-y-2">
                    <div class="flex items-center gap-2">
                      <span class="inline-flex items-center rounded-full border border-danger/30 bg-danger-light px-2 py-0.5 text-xs font-medium text-danger">
                        failed
                      </span>
                      <span class="text-xs text-stone-500">{linkedModel.name}</span>
                    </div>
                    <a
                      href={localizeHref(`/projects/${projectId}/models`)}
                      class="inline-flex items-center gap-1.5 rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-xs font-medium
                             text-stone-600 transition-colors hover:bg-stone-50 dark:border-stone-600 dark:hover:bg-stone-700"
                    >
                      View in Models
                    </a>
                  </div>
                {/if}
              </div>

              <!-- CreateModelFromSessionDialog for this species -->
              {#if trainDialogSpeciesIndex === idx}
                <CreateModelFromSessionDialog
                  {projectId}
                  {session}
                  speciesConfig={spConfig}
                  open={true}
                  onClose={() => { trainDialogSpeciesIndex = null; }}
                  onSuccess={handleCreateModelSuccess}
                />
              {/if}
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  {/if}
</div>
