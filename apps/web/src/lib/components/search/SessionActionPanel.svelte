<script lang="ts">
  /**
   * SessionActionPanel - Header card + action buttons for SearchSessionDetail.
   *
   * Extracted from SearchSessionDetail.svelte as Step 3 of the P2-B split
   * (see plan.md §6 / §7). Renders:
   *   - The session header card (name + inline rename UI, status/meta row,
   *     Export CSV button, failed-session error message).
   *   - The optional reference audio area, passed in via a `referenceAudio`
   *     snippet so the parent keeps ownership of species + model-name data.
   *   - The "Fork" / "Edit & Re-search" action buttons (only when the session
   *     is completed and reconstruction produced at least one species).
   *
   * The component is near-stateless: the only local state is the rename
   * input DOM ref and a `prevIsRenaming` edge tracker used to focus + select
   * the input on the rising edge of `rename.isRenaming` (plan.md §5.2).
   *
   * Explicitly NOT owned here:
   *   - Rename state + side-effects — lives in `useSessionRename` and is
   *     forwarded via the `rename` prop (narrowed with `Pick` so the child
   *     cannot call `dispose()` — plan.md §6.1 / Codex v2 Med-3).
   *   - Reconstruction state / derived display strings — lives in
   *     `useSessionReconstruction`; the parent forwards the required values
   *     as plain props (derived ones as `() => T` getters so reactivity is
   *     preserved across the boundary).
   */

  import type { Snippet } from 'svelte';
  import * as m from '$lib/paraglide/messages';
  import type { SearchSession } from '$lib/types/search';
  import type { SessionRenameHookApi } from './types';

  interface Props {
    /** Current session (non-null — parent only renders this panel after load). */
    session: SearchSession;

    // --- Reconstruction-derived display values (function getters so Svelte
    // tracks dependency reads on each call, matching the pre-refactor
    // call sites in SearchSessionDetail.svelte). ---------------------------
    statusLabel: () => string;
    statusColor: () => string;
    statusDotColor: () => string;
    sessionName: () => string;
    formattedDate: () => string;
    searchDuration: () => number;

    /** Resolved dataset name (null if unavailable / still loading). */
    datasetName: string | null;

    /**
     * True iff the session is completed AND the reconstruction produced at
     * least one species. Drives visibility of the Fork / Edit & Re-search
     * action buttons. Computed by the parent so this component stays free
     * of reconstruction internals.
     */
    hasEditableRerun: boolean;

    /**
     * Rename hook API — narrowed with `Pick` so the child cannot reach
     * `dispose()` or any field added later. See plan.md §6.1 / Codex v2 Med-3.
     */
    rename: Pick<
      SessionRenameHookApi,
      | 'isRenaming'
      | 'renameValue'
      | 'isSavingRename'
      | 'renameError'
      | 'setRenameValue'
      | 'startRename'
      | 'cancelRename'
      | 'saveRename'
      | 'handleRenameKeydown'
    >;

    /** True while the CSV export request is in flight. */
    isExportingRecordings: boolean;
    /** Click handler for the Export CSV button. */
    onExportRecordings: () => void;
    /** Click handler for the "Edit & Re-search" button. */
    onEditRerun: () => void;
    /** Click handler for the "Fork as New Session" button. */
    onFork: () => void;

    /** Optional reference audio block rendered between the header and action row. */
    referenceAudio?: Snippet;
  }

  let {
    session,
    statusLabel,
    statusColor,
    statusDotColor,
    sessionName,
    formattedDate,
    searchDuration,
    datasetName,
    hasEditableRerun,
    rename,
    isExportingRecordings,
    onExportRecordings,
    onEditRerun,
    onFork,
    referenceAudio,
  }: Props = $props();

  // --- Rename input focus management (plan.md §5.2 / §13.4) --------------
  //
  // The rename hook is DOM-agnostic, so the input ref + focus scheduling
  // live here. We focus + select on the rising edge (false → true) of
  // `rename.isRenaming` only; re-renders that keep `isRenaming` true must
  // NOT steal focus back from the user. `$effect` runs after Svelte commits
  // the DOM update so the <input> is guaranteed mounted — no setTimeout
  // needed (this matches the pre-refactor behaviour where the parent also
  // used `$effect`, not a setTimeout).
  let renameInputEl = $state<HTMLInputElement | null>(null);
  let prevIsRenaming = $state(false);

  $effect(() => {
    const now = rename.isRenaming;
    if (now && !prevIsRenaming) {
      renameInputEl?.focus();
      renameInputEl?.select();
    }
    prevIsRenaming = now;
  });
</script>

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
            {sessionName()}
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
          onclick={onExportRecordings}
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

<!-- Reference audio section (rendered by the parent via snippet). -->
{#if referenceAudio}
  {@render referenceAudio()}
{/if}

<!-- Action buttons (for completed sessions with reconstructable species). -->
{#if hasEditableRerun}
  <div class="flex items-center justify-end gap-2">
    <!-- Fork: create a brand-new session preserving old results -->
    <button
      type="button"
      class="inline-flex items-center gap-2 rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium
             text-stone-500 shadow-sm transition-colors hover:bg-stone-50 hover:text-stone-700
             dark:border-stone-600 dark:hover:bg-stone-700 dark:hover:text-stone-300"
      onclick={onFork}
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
      onclick={onEditRerun}
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
