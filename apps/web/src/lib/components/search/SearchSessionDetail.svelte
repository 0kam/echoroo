<script lang="ts">
  /**
   * SearchSessionDetail - Full detail view for a persisted search session.
   *
   * Displays the session header (name, date, status, result count, duration),
   * the reconstructed reference audio in readonly mode, a re-run button, and
   * the full results panel.
   */

  import { onMount } from 'svelte';
  import * as m from '$lib/paraglide/messages';
  import { getSearchSession, getReferenceAudioUrl, updateSearchSession } from '$lib/api/search';
  import { generateId } from '$lib/utils/id';
  import type { SearchSession, TargetSpecies, SoundSource } from '$lib/types/search';
  import ReferenceSoundsPanel from './ReferenceSoundsPanel.svelte';
  import ResultsPanel from './ResultsPanel.svelte';
  import SearchSessionExportButton from './SearchSessionExportButton.svelte';

  interface Props {
    projectId: string;
    sessionId: string;
    onBack: () => void;
    onRerun: (species: TargetSpecies[]) => void;
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
      const data = await getSearchSession(pid, sid);
      session = data;

      // Reconstruct reference audio sources from persisted session data
      if (data.species_config && data.reference_audio_keys && data.reference_audio_keys.length > 0) {
        const loaded: TargetSpecies[] = [];

        for (const spConfig of data.species_config) {
          const speciesSources = (spConfig.sources ?? []).reduce<SoundSource[]>((acc, srcConfig) => {
            const s3Key = (srcConfig as Record<string, unknown>)['s3_key'] as string | undefined;
            if (s3Key) {
              const keyIndex = data.reference_audio_keys!.indexOf(s3Key);
              if (keyIndex >= 0) {
                const fileKey = (srcConfig as Record<string, unknown>)['file_key'] as string | undefined;
                acc.push({
                  id: generateId(),
                  origin: 's3' as const,
                  label: fileKey ?? `Source ${keyIndex + 1}`,
                  streamUrl: getReferenceAudioUrl(pid, sid, keyIndex),
                  sourceIndex: keyIndex,
                  start_time: (srcConfig as Record<string, unknown>)['start_time'] as number | undefined,
                  end_time: (srcConfig as Record<string, unknown>)['end_time'] as number | undefined,
                });
              }
            }
            return acc;
          }, []);

          if (speciesSources.length > 0) {
            loaded.push({
              id: generateId(),
              tag_id: spConfig.tag_id,
              scientific_name: spConfig.scientific_name,
              common_name: spConfig.common_name ?? undefined,
              sources: speciesSources,
            });
          }
        }

        reconstructedSpecies = loaded;
      }
    } catch (e) {
      loadError = e instanceof Error ? e.message : m.search_error_search_failed();
    } finally {
      isLoading = false;
    }
  }

  onMount(() => {
    loadSession(projectId, sessionId);
  });

  // Reload when sessionId changes
  $effect(() => {
    loadSession(projectId, sessionId);
  });

  // ============================================
  // Derived
  // ============================================

  const statusLabel = $derived(() => {
    if (!session) return '';
    switch (session.status) {
      case 'completed': return m.search_session_status_completed();
      case 'running':   return m.search_session_status_running();
      case 'failed':    return m.search_session_status_failed();
      case 'pending':   return m.search_session_status_pending();
      default:          return session.status;
    }
  });

  const statusColor = $derived(() => {
    if (!session) return 'text-stone-500';
    switch (session.status) {
      case 'completed': return 'text-emerald-600 dark:text-emerald-400';
      case 'running':   return 'text-blue-600 dark:text-blue-400';
      case 'failed':    return 'text-red-600 dark:text-red-400';
      case 'pending':   return 'text-amber-600 dark:text-amber-400';
      default:          return 'text-stone-500';
    }
  });

  const statusDotColor = $derived(() => {
    if (!session) return 'bg-stone-400';
    switch (session.status) {
      case 'completed': return 'bg-emerald-500';
      case 'running':   return 'bg-blue-500 animate-pulse';
      case 'failed':    return 'bg-red-500';
      case 'pending':   return 'bg-amber-500';
      default:          return 'bg-stone-400';
    }
  });

  const sessionName = $derived(() => {
    if (!session) return '';
    if (session.name) return session.name;
    if (session.species_config && session.species_config.length > 0) {
      return session.species_config
        .map((sp) => sp.common_name ?? sp.scientific_name)
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

  const totalMatches = $derived(() => {
    if (!session?.results) return 0;
    return session.results.total_matches;
  });

  // ============================================
  // Handlers
  // ============================================

  function handleRerun() {
    if (reconstructedSpecies.length === 0) return;

    // Deep-clone so edits don't affect the readonly display
    const cloned: TargetSpecies[] = reconstructedSpecies.map((sp) => ({
      ...sp,
      sources: [...sp.sources],
    }));

    onRerun(cloned);
  }

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
  // Edit & Re-search handler
  // ============================================

  function handleEditRerun() {
    if (reconstructedSpecies.length === 0) return;

    // Deep-clone so edits in new-search mode don't affect this detail view
    const cloned: TargetSpecies[] = reconstructedSpecies.map((sp) => ({
      ...sp,
      id: generateId(),
      sources: sp.sources.map((src) => ({ ...src, id: generateId() })),
    }));

    onRerun(cloned);
  }
</script>

<div class="space-y-6">
  <!-- Back navigation -->
  <div>
    <button
      type="button"
      class="inline-flex items-center gap-1.5 text-sm text-stone-500 transition-colors hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
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
      <div class="rounded-lg border border-stone-200 bg-white p-6 shadow-sm dark:border-stone-700 dark:bg-stone-900">
        <div class="mb-2 h-6 w-2/5 animate-pulse rounded bg-stone-200 dark:bg-stone-700"></div>
        <div class="h-4 w-1/3 animate-pulse rounded bg-stone-100 dark:bg-stone-800"></div>
      </div>
      <!-- Reference audio skeleton -->
      <div class="rounded-lg border border-stone-200 bg-white p-6 shadow-sm dark:border-stone-700 dark:bg-stone-900">
        <div class="mb-4 h-5 w-1/4 animate-pulse rounded bg-stone-200 dark:bg-stone-700"></div>
        <div class="h-20 animate-pulse rounded bg-stone-100 dark:bg-stone-800"></div>
      </div>
      <!-- Results skeleton -->
      <div class="rounded-lg border border-stone-200 bg-white p-6 shadow-sm dark:border-stone-700 dark:bg-stone-900">
        <div class="mb-4 h-5 w-1/4 animate-pulse rounded bg-stone-200 dark:bg-stone-700"></div>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {#each { length: 8 } as _}
            <div class="animate-pulse overflow-hidden rounded-lg border border-stone-200 bg-white shadow-sm dark:border-stone-700 dark:bg-stone-900">
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
    <div class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400">
      {loadError}
    </div>

  {:else if session}
    <!-- Session header card -->
    <div class="rounded-lg border border-stone-200 bg-white p-5 shadow-sm dark:border-stone-700 dark:bg-stone-900">
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
                class="min-w-0 flex-1 rounded-md border border-stone-300 bg-white px-3 py-1.5 text-lg font-semibold text-stone-900
                       shadow-sm outline-none ring-primary-500 focus:border-primary-500 focus:ring-2
                       dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
                disabled={isSavingRename}
                onkeydown={handleRenameKeydown}
              />
              <button
                type="button"
                class="shrink-0 rounded-md bg-primary-600 px-3 py-1.5 text-sm font-medium text-white
                       transition-colors hover:bg-primary-700 disabled:opacity-50
                       dark:bg-primary-500 dark:hover:bg-primary-600"
                disabled={isSavingRename || !renameValue.trim()}
                onclick={saveRename}
              >
                {isSavingRename ? m.search_rename_saving() : m.search_rename_save()}
              </button>
              <button
                type="button"
                class="shrink-0 rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm font-medium
                       text-stone-700 transition-colors hover:bg-stone-50 disabled:opacity-50
                       dark:border-stone-600 dark:bg-stone-800 dark:text-stone-300 dark:hover:bg-stone-700"
                disabled={isSavingRename}
                onclick={cancelRename}
              >
                {m.search_rename_cancel()}
              </button>
            </div>
            {#if renameError}
              <p class="mt-1 text-sm text-red-600 dark:text-red-400">{renameError}</p>
            {/if}
          {:else}
            <div class="flex items-center gap-2">
              <h2 class="truncate text-xl font-semibold text-stone-900 dark:text-stone-100">
                {sessionName()}
              </h2>
              {#if session.status === 'completed'}
                <button
                  type="button"
                  title={m.search_rename_session()}
                  aria-label={m.search_rename_session()}
                  class="shrink-0 rounded p-1 text-stone-400 transition-colors hover:text-stone-700
                         dark:text-stone-500 dark:hover:text-stone-300"
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
          <p class="mt-0.5 text-sm text-stone-500 dark:text-stone-400">
            {formattedDate()}
          </p>

          <!-- Status + meta row -->
          <div class="mt-2 flex flex-wrap items-center gap-3 text-sm">
            <!-- Status badge -->
            <span class="inline-flex items-center gap-1.5 font-medium {statusColor()}">
              <span class="inline-block h-2 w-2 rounded-full {statusDotColor()}"></span>
              {statusLabel()}
            </span>

            {#if session.result_count > 0}
              <span class="text-stone-400">·</span>
              <span class="text-stone-600 dark:text-stone-300">
                {m.search_session_results_summary({ results: String(session.result_count) })}
              </span>
            {/if}

            {#if session.confirmed_count > 0 || session.rejected_count > 0}
              <span class="text-stone-400">·</span>
              <span class="text-emerald-600 dark:text-emerald-400">
                ✓ {session.confirmed_count}
              </span>
              <span class="text-red-500 dark:text-red-400">
                ✗ {session.rejected_count}
              </span>
            {/if}

            {#if searchDuration() > 0}
              <span class="text-stone-400">·</span>
              <span class="text-stone-500 dark:text-stone-400">
                {m.search_search_duration({ ms: String(searchDuration()) })}
              </span>
            {/if}
          </div>
        </div>

        <!-- CSV export button -->
        {#if session.status === 'completed' && session.result_count > 0}
          <SearchSessionExportButton {projectId} sessionId={session.id} />
        {/if}
      </div>

      <!-- Error message for failed sessions -->
      {#if session.status === 'failed' && session.error_message}
        <div class="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400">
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

      <!-- Action buttons (only for completed sessions with reference audio) -->
      {#if session.status === 'completed'}
        <div class="flex items-center justify-end gap-2">
          <!-- Edit & Re-search: clone session as template and switch to new-search mode -->
          <button
            type="button"
            class="inline-flex items-center gap-2 rounded-md border border-stone-300 bg-white px-4 py-2 text-sm font-medium
                   text-stone-700 shadow-sm transition-colors hover:bg-stone-50
                   dark:border-stone-600 dark:bg-stone-800 dark:text-stone-300 dark:hover:bg-stone-700"
            onclick={handleEditRerun}
          >
            <!-- Edit icon -->
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" stroke-linecap="round" stroke-linejoin="round" />
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            {m.search_edit_rerun()}
          </button>

          <!-- Re-run: use same sources exactly, pass source_session_id -->
          <button
            type="button"
            class="inline-flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium
                   text-white shadow-sm transition-colors hover:bg-primary-700
                   dark:bg-primary-500 dark:hover:bg-primary-600"
            onclick={handleRerun}
          >
            <!-- Refresh icon -->
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M1 4v6h6M23 20v-6h-6" stroke-linecap="round" stroke-linejoin="round" />
              <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            {m.search_add_sources_rerun()}
          </button>
        </div>
      {/if}
    {/if}

    <!-- Results section -->
    {#if session.status === 'completed' && session.results}
      <ResultsPanel
        {projectId}
        results={session.results.results}
        totalMatches={totalMatches()}
        searchDurationMs={searchDuration()}
        isSearching={false}
        searchingSpecies={reconstructedSpecies}
        searchSessionId={session.id}
      />
    {:else if session.status === 'failed'}
      <!-- Failed state - no results -->
      <div class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-stone-200 py-12 text-center dark:border-stone-700">
        <svg
          class="mx-auto mb-3 h-10 w-10 text-red-300 dark:text-red-700"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="1.5"
          aria-hidden="true"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
        </svg>
        <p class="font-medium text-stone-500 dark:text-stone-400">{m.search_session_status_failed()}</p>
      </div>
    {:else if session.status === 'pending' || session.status === 'running'}
      <!-- Pending/running state -->
      <div class="flex items-center justify-center gap-3 rounded-lg border border-stone-200 bg-white p-6 text-sm text-stone-600 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-400">
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
          class="mx-auto mb-3 h-10 w-10 text-stone-300 dark:text-stone-600"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="1.5"
          aria-hidden="true"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
        </svg>
        <p class="font-medium text-stone-500 dark:text-stone-400">{m.search_results_no_matches()}</p>
        <p class="mt-1 text-sm text-stone-400 dark:text-stone-500">{m.search_results_no_matches_hint()}</p>
      </div>
    {/if}
  {/if}
</div>
