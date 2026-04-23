<script lang="ts">
  /**
   * SearchSessionDetail - Full detail view for a persisted search session.
   *
   * Displays the session header (name, date, status, result count, duration),
   * the reconstructed reference audio in readonly mode, a re-run button, and
   * the full results panel.
   */

  import { onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages';
  import { getLocale, localizeHref } from '$lib/paraglide/runtime';
  import { goto } from '$app/navigation';
  import { exportSearchSessionRecordingsCSV } from '$lib/api/search';
  import { generateId } from '$lib/utils/id';
  import type { TargetSpecies, SpeciesMatchResult } from '$lib/types/search';
  import ReferenceSoundsPanel from './ReferenceSoundsPanel.svelte';
  import ResultsPanel from './ResultsPanel.svelte';
  import CreateModelFromSessionDialog from './CreateModelFromSessionDialog.svelte';
  import SessionActionPanel from './SessionActionPanel.svelte';
  import { useSessionReconstruction } from './useSessionReconstruction.svelte';
  import { useSessionRename } from './useSessionRename.svelte';

  interface Props {
    projectId: string;
    sessionId: string;
    onBack: () => void;
    onRerun: (species: TargetSpecies[], editingSessionId: string | null, datasetId?: string) => void;
  }

  let { projectId, sessionId, onBack, onRerun }: Props = $props();

  // ============================================
  // Session reconstruction hook (plan.md §4)
  // Owns: session, isLoading, loadError, reconstructedSpecies,
  //       sessionModels, datasetName, + 6 derived display values.
  // ============================================

  const reconstruction = useSessionReconstruction({
    projectId: () => projectId,
    sessionId: () => sessionId,
  });

  // ============================================
  // Session rename hook (plan.md §5)
  // Owns: isRenaming, renameValue, isSavingRename, renameError +
  //       startRename / cancelRename / saveRename / handleRenameKeydown.
  // ============================================

  const rename = useSessionRename({
    session: () => reconstruction.session,
    projectId: () => projectId,
    getDisplayName: () => {
      // Prefer the explicit session.name when present; fall back to the
      // hook's computed display name (species list or default label).
      const current = reconstruction.session;
      return current?.name ?? reconstruction.sessionName();
    },
    onRenameSuccess: (updated) => reconstruction.setSession(updated),
  });

  onDestroy(() => {
    reconstruction.dispose();
    rename.dispose();
  });

  // ============================================
  // Parent-owned state (not delegated to a hook — used only here).
  // ============================================

  // Currently selected species key (tracked from ResultsPanel)
  let _currentSpeciesKey = $state<string | null>(null);

  /** Species key for the currently open "Train Model" dialog */
  let trainDialogSpeciesKey = $state<string | null>(null);
  /** Species metadata for the currently open "Train Model" dialog */
  let trainDialogSpeciesMeta = $state<SpeciesMatchResult | null>(null);

  function handleCreateModelSuccess(modelId: string, _opts?: { samplingFailed?: boolean; error?: string }) {
    trainDialogSpeciesKey = null;
    trainDialogSpeciesMeta = null;
    // Navigate to the new model in the Models tab
    goto(localizeHref(`/projects/${projectId}/models?model=${modelId}`));
  }

  // Recordings CSV export state
  let isExportingRecordings = $state(false);

  async function handleExportRecordings() {
    const current = reconstruction.session;
    if (!current) return;
    isExportingRecordings = true;
    try {
      await exportSearchSessionRecordingsCSV(projectId, current.id, getLocale());
    } catch (e) {
      console.error('Recordings export failed:', e);
    } finally {
      isExportingRecordings = false;
    }
  }

  // Rename input focus management lives in SessionActionPanel.svelte — the
  // hook is DOM-agnostic and the panel owns the <input> ref + the
  // rising-edge `$effect` (plan.md §5.2 / §13.4).

  // ============================================
  // Edit & Re-search handler (updates existing session in-place)
  // ============================================

  function handleEditRerun() {
    const current = reconstruction.session;
    const species = reconstruction.reconstructedSpecies;
    if (species.length === 0 || !current) return;

    // Deep-clone so edits in new-search mode don't affect this detail view
    const cloned: TargetSpecies[] = species.map((sp) => ({
      ...sp,
      id: generateId(),
      sources: sp.sources.map((src) => ({ ...src, id: generateId() })),
    }));

    // Pass the session ID and dataset_id so the parent restores the correct config
    onRerun(cloned, current.id, current.parameters?.dataset_id ?? undefined);
  }

  // ============================================
  // Fork handler (creates a brand-new session)
  // ============================================

  function handleFork() {
    const species = reconstruction.reconstructedSpecies;
    if (species.length === 0) return;

    // Deep-clone — pass null session ID to signal "create new"
    const cloned: TargetSpecies[] = species.map((sp) => ({
      ...sp,
      id: generateId(),
      sources: sp.sources.map((src) => ({ ...src, id: generateId() })),
    }));

    onRerun(cloned, null, reconstruction.session?.parameters?.dataset_id ?? undefined);
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

  {#if reconstruction.isLoading}
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

  {:else if reconstruction.loadError}
    <!-- Error state -->
    <div class="rounded-lg border border-danger/30 bg-danger-light p-4 text-sm text-danger">
      {reconstruction.loadError}
    </div>

  {:else if reconstruction.session}
    {@const session = reconstruction.session}
    {@const reconstructedSpecies = reconstruction.reconstructedSpecies}
    {@const sessionModels = reconstruction.sessionModels}

    <!-- Header card + reference audio + action buttons (plan.md §6 / §7) -->
    <SessionActionPanel
      {session}
      statusLabel={reconstruction.statusLabel}
      statusColor={reconstruction.statusColor}
      statusDotColor={reconstruction.statusDotColor}
      sessionName={reconstruction.sessionName}
      formattedDate={reconstruction.formattedDate}
      searchDuration={reconstruction.searchDuration}
      datasetName={reconstruction.datasetName}
      hasEditableRerun={session.status === 'completed' && reconstructedSpecies.length > 0}
      {rename}
      {isExportingRecordings}
      onExportRecordings={handleExportRecordings}
      onEditRerun={handleEditRerun}
      onFork={handleFork}
    >
      {#snippet referenceAudio()}
        {#if reconstructedSpecies.length > 0}
          <ReferenceSoundsPanel
            {projectId}
            species={reconstructedSpecies}
            modelName={session.model_name}
            onSpeciesChange={() => {}}
            readonly={true}
          />
        {/if}
      {/snippet}
    </SessionActionPanel>

    <!-- Results section -->
    {#if session.status === 'completed' && session.results}
      <ResultsPanel
        {projectId}
        sessionId={session.id}
        results={session.results.results}
        searchDurationMs={reconstruction.searchDuration()}
        isSearching={false}
        searchingSpecies={reconstructedSpecies}
        onSpeciesKeyChange={(key) => { _currentSpeciesKey = key; }}
        onTrainModelRequest={(key, meta) => {
          trainDialogSpeciesKey = key;
          trainDialogSpeciesMeta = meta;
        }}
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

    <!-- Linked Models (compact status badges) -->
    {#if session.status === 'completed' && sessionModels.length > 0}
      <div class="rounded-lg border border-stone-200 bg-surface-card p-4 shadow-sm dark:border-stone-700">
        <h3 class="mb-3 text-sm font-semibold text-stone-700 dark:text-stone-300">
          {m.models_linked_models()}
        </h3>
        <div class="space-y-2">
          {#each sessionModels as mdl (mdl.id)}
            <div class="flex items-center gap-3 rounded-lg border border-stone-100 px-3 py-2 dark:border-stone-800">
              {#if mdl.status === 'training'}
                <span class="inline-flex items-center gap-1 rounded-full border border-info/40 bg-info-light px-2 py-0.5 text-xs font-medium text-info">
                  <svg class="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                  </svg>
                  {mdl.status}
                </span>
              {:else if mdl.status === 'trained' || mdl.status === 'deployed'}
                <span class="inline-flex items-center rounded-full border border-success/30 bg-success-light px-2 py-0.5 text-xs font-medium text-success">
                  {mdl.status}
                </span>
              {:else if mdl.status === 'failed'}
                <span class="inline-flex items-center rounded-full border border-danger/30 bg-danger-light px-2 py-0.5 text-xs font-medium text-danger">
                  {mdl.status}
                </span>
              {:else}
                <span class="inline-flex items-center rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-xs font-medium text-stone-600 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-400">
                  {mdl.status}
                </span>
              {/if}
              <span class="text-sm text-stone-600 dark:text-stone-400">{mdl.name}</span>
              <a
                href={localizeHref(`/projects/${projectId}/models?model=${mdl.id}`)}
                class="ml-auto inline-flex items-center gap-1 text-xs text-primary-600 transition-colors hover:text-primary-700 dark:text-primary-400"
              >
                {m.models_view_in_models()}
                <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              </a>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Single instance of CreateModelFromSessionDialog — opened from ResultsPanel's Train button -->
    {#if trainDialogSpeciesKey !== null && trainDialogSpeciesMeta !== null && session}
      <CreateModelFromSessionDialog
        {projectId}
        {session}
        speciesConfig={{
          tag_id: trainDialogSpeciesMeta.tag_id ?? null,
          scientific_name: trainDialogSpeciesMeta.scientific_name,
          common_name: trainDialogSpeciesMeta.common_name ?? null,
        }}
        open={trainDialogSpeciesKey !== null}
        onClose={() => { trainDialogSpeciesKey = null; trainDialogSpeciesMeta = null; }}
        onSuccess={handleCreateModelSuccess}
      />
    {/if}
  {/if}
</div>
