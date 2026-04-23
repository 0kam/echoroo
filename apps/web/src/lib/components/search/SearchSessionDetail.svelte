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
  // Parent-owned state (will move in Steps 2/3)
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

  // Rename input DOM ref. The hook is DOM-agnostic so focus management
  // lives here (Step 3 will move this into SessionActionPanel.svelte).
  let renameInputEl = $state<HTMLInputElement | null>(null);

  // Rising-edge focus: when `rename.isRenaming` transitions false → true,
  // focus + select the input. `$effect` runs after Svelte commits the DOM
  // update, so the <input> is guaranteed mounted — no setTimeout needed
  // (plan.md §5.2).
  let prevIsRenaming = $state(false);
  $effect(() => {
    const now = rename.isRenaming;
    if (now && !prevIsRenaming) {
      renameInputEl?.focus();
      renameInputEl?.select();
    }
    prevIsRenaming = now;
  });

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
    {@const datasetName = reconstruction.datasetName}
    <!-- Session header card -->
    <div class="rounded-lg border border-stone-200 bg-surface-card p-5 shadow-sm dark:border-stone-700">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0 flex-1">
          <!-- Session name with inline rename -->
          {#if rename.isRenaming}
            <div class="flex items-center gap-2">
              <input
                bind:this={renameInputEl}
                value={rename.renameValue}
                oninput={(e) => rename.setRenameValue(e.currentTarget.value)}
                type="text"
                aria-label={m.search_session_name()}
                class="min-w-0 flex-1 rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-lg font-semibold text-stone-900
                       shadow-sm outline-none ring-primary-500 focus:border-primary-500 focus:ring-2
                       dark:border-stone-600"
                disabled={rename.isSavingRename}
                onkeydown={rename.handleRenameKeydown}
              />
              <button
                type="button"
                class="shrink-0 rounded-md bg-primary-600 px-3 py-1.5 text-sm font-medium text-white
                       transition-colors hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2
                       disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
                disabled={rename.isSavingRename || !rename.renameValue.trim()}
                onclick={rename.saveRename}
              >
                {rename.isSavingRename ? m.search_rename_saving() : m.search_rename_save()}
              </button>
              <button
                type="button"
                class="shrink-0 rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm font-medium
                       text-stone-700 transition-colors hover:bg-stone-50 dark:hover:bg-stone-700 disabled:opacity-50
                       dark:border-stone-600"
                disabled={rename.isSavingRename}
                onclick={rename.cancelRename}
              >
                {m.search_rename_cancel()}
              </button>
            </div>
            {#if rename.renameError}
              <p class="mt-1 text-sm text-danger">{rename.renameError}</p>
            {/if}
          {:else}
            <div class="flex items-center gap-2">
              <h2 class="truncate text-xl font-semibold text-stone-900">
                {reconstruction.sessionName()}
              </h2>
              {#if session.status === 'completed'}
                <button
                  type="button"
                  title={m.search_rename_session()}
                  aria-label={m.search_rename_session()}
                  class="shrink-0 rounded p-1 text-stone-400 transition-colors hover:text-stone-700
                         dark:hover:text-stone-300"
                  onclick={rename.startRename}
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
            {reconstruction.formattedDate()}
          </p>

          <!-- Status + meta row -->
          <div class="mt-2 flex flex-wrap items-center gap-3 text-sm">
            <!-- Status badge -->
            <span class="inline-flex items-center gap-1.5 font-medium {reconstruction.statusColor()}">
              <span class="inline-block h-2 w-2 rounded-full {reconstruction.statusDotColor()}"></span>
              {reconstruction.statusLabel()}
            </span>

            {#if datasetName}
              <span class="text-stone-400">·</span>
              <span class="text-stone-500">{datasetName}</span>
            {/if}

            {#if session.model_name}
              <span class="text-stone-400">·</span>
              <span class="rounded bg-stone-100 px-1.5 py-0.5 text-xs font-medium text-stone-600 dark:bg-stone-700 dark:text-stone-300">{session.model_name}</span>
            {/if}

            {#if reconstruction.searchDuration() > 0}
              <span class="text-stone-400">·</span>
              <span class="text-stone-500">
                {m.search_search_duration({ ms: String(reconstruction.searchDuration()) })}
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
