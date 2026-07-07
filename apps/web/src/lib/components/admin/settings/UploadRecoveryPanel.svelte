<script lang="ts">
  /**
   * Upload recovery panel (subsection of the maintenance card).
   *
   * Self-contained: fetches the wedged (non-terminal) upload sessions from the
   * superuser BFF and renders them in a table. Each row exposes a danger
   * "Force fail" action (confirm modal) that transitions the session to a
   * terminal state via `POST /admin/uploads/{id}/fail`. On success the row is
   * refetched; a 409 is surfaced as an informative notice (the session may have
   * completed concurrently — that is expected, not a bug). Owns its own
   * loading / notice state so it does not depend on the parent's shared banners.
   */

  import { adminApi, type StuckUploadSessionSummary } from '$lib/api/admin';
  import { ApiError } from '$lib/api/client';
  import { getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  let sessions = $state<StuckUploadSessionSummary[]>([]);
  let isLoading = $state(false);
  let loadError = $state<string | null>(null);
  let hasLoaded = $state(false);

  // Force-fail action state.
  let confirmSession = $state<StuckUploadSessionSummary | null>(null);
  let failingId = $state<string | null>(null);
  let actionError = $state<string | null>(null);
  let actionNotice = $state<string | null>(null);

  /**
   * Fetch the current page of stuck upload sessions.
   */
  async function loadStuckSessions() {
    isLoading = true;
    loadError = null;
    actionError = null;
    actionNotice = null;

    try {
      const response = await adminApi.listStuckUploads();
      sessions = response.items;
      hasLoaded = true;
    } catch (err) {
      if (err instanceof ApiError) {
        loadError = err.detail || err.message;
      } else {
        loadError = m.admin_settings_uploads_error_load();
      }
    } finally {
      isLoading = false;
    }
  }

  /**
   * Force-fail the session selected in the confirmation modal.
   *
   * On success the returned summary replaces the row; a 409 (already terminal
   * / concurrent transition) is surfaced as an informative notice and the row
   * is removed since it is no longer stuck.
   */
  async function handleConfirmForceFail() {
    const target = confirmSession;
    confirmSession = null;
    if (!target) return;

    failingId = target.id;
    actionError = null;
    actionNotice = null;

    try {
      const updated = await adminApi.forceFailUpload(target.id);
      // The session is now terminal — drop it from the stuck list.
      sessions = sessions.filter((session) => session.id !== updated.id);
      actionNotice = m.admin_settings_uploads_force_fail_success({
        id: shortId(updated.id),
      });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          // Concurrent transition / already terminal: informative, not a bug.
          actionNotice = err.detail || m.admin_settings_uploads_force_fail_conflict();
          sessions = sessions.filter((session) => session.id !== target.id);
        } else {
          actionError = err.detail || err.message;
        }
      } else {
        actionError = m.admin_settings_uploads_force_fail_error();
      }
    } finally {
      failingId = null;
    }
  }

  /**
   * Shorten a UUID for compact table display (first segment).
   */
  function shortId(id: string): string {
    return id.split('-')[0] ?? id;
  }

  /**
   * Format an ISO timestamp using the active locale.
   */
  function formatDate(dateString: string): string {
    return new Date(dateString).toLocaleString(getLocale());
  }
</script>

<!-- Upload recovery -->
<div>
  <div class="flex items-center justify-between gap-4">
    <div class="flex-1">
      <h3 class="text-sm font-medium text-stone-700">
        {m.admin_settings_uploads_label()}
      </h3>
      <p class="mt-1 text-sm text-stone-500">
        {m.admin_settings_uploads_hint()}
      </p>
    </div>
    <button
      type="button"
      onclick={loadStuckSessions}
      disabled={isLoading}
      class="inline-flex flex-shrink-0 items-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 shadow-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {#if isLoading}
        <svg
          class="mr-2 h-4 w-4 animate-spin"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle
            class="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            stroke-width="4"
          ></circle>
          <path
            class="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          ></path>
        </svg>
        {m.admin_settings_uploads_loading()}
      {:else}
        {m.admin_settings_uploads_refresh()}
      {/if}
    </button>
  </div>

  <!-- Load error -->
  {#if loadError}
    <div class="mt-4 rounded-md bg-danger-light p-3" role="alert">
      <p class="text-sm font-medium text-danger">{loadError}</p>
    </div>
  {/if}

  <!-- Force-fail action notice (informative, e.g. 409) -->
  {#if actionNotice}
    <div class="mt-4 rounded-md bg-info-light p-3" role="status">
      <p class="text-sm font-medium text-info">{actionNotice}</p>
    </div>
  {/if}

  <!-- Force-fail action error -->
  {#if actionError}
    <div class="mt-4 rounded-md bg-danger-light p-3" role="alert">
      <p class="text-sm font-medium text-danger">{actionError}</p>
    </div>
  {/if}

  {#if !hasLoaded}
    <p class="mt-4 text-sm text-stone-500">
      {m.admin_settings_uploads_not_loaded()}
    </p>
  {:else if sessions.length === 0}
    <p class="mt-4 text-sm text-stone-500">
      {m.admin_settings_uploads_empty()}
    </p>
  {:else}
    <div class="mt-4 overflow-x-auto">
      <table class="min-w-full divide-y divide-stone-200 text-sm">
        <thead>
          <tr class="text-left text-xs font-medium uppercase tracking-wider text-stone-500">
            <th class="px-3 py-2">{m.admin_settings_uploads_col_session()}</th>
            <th class="px-3 py-2">{m.admin_settings_uploads_col_project()}</th>
            <th class="px-3 py-2">{m.admin_settings_uploads_col_dataset()}</th>
            <th class="px-3 py-2">{m.admin_settings_uploads_col_status()}</th>
            <th class="px-3 py-2">{m.admin_settings_uploads_col_updated()}</th>
            <th class="px-3 py-2">{m.admin_settings_uploads_col_files()}</th>
            <th class="px-3 py-2">{m.admin_settings_uploads_col_error()}</th>
            <th class="px-3 py-2 text-right">{m.admin_settings_uploads_col_actions()}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-stone-100">
          {#each sessions as session (session.id)}
            <tr>
              <td class="px-3 py-2 font-mono text-xs text-stone-700" title={session.id}>
                {shortId(session.id)}
              </td>
              <td class="px-3 py-2 font-mono text-xs text-stone-700" title={session.project_id}>
                {shortId(session.project_id)}
              </td>
              <td class="px-3 py-2 font-mono text-xs text-stone-700" title={session.dataset_id}>
                {shortId(session.dataset_id)}
              </td>
              <td class="px-3 py-2">
                <span
                  class="inline-flex items-center rounded-full bg-warning-light px-2 py-0.5 text-xs font-medium text-warning"
                >
                  {session.status}
                </span>
              </td>
              <td class="px-3 py-2 whitespace-nowrap text-xs text-stone-600" title={session.updated_at}>
                {formatDate(session.updated_at)}
              </td>
              <td class="px-3 py-2 whitespace-nowrap text-xs text-stone-600">
                {session.imported_files} / {session.validated_files} / {session.total_files}
              </td>
              <td class="max-w-xs px-3 py-2">
                {#if session.error}
                  <span class="block truncate text-xs text-danger" title={session.error}>
                    {session.error}
                  </span>
                {:else}
                  <span class="text-xs text-stone-400">—</span>
                {/if}
              </td>
              <td class="px-3 py-2 text-right">
                <button
                  type="button"
                  onclick={() => (confirmSession = session)}
                  disabled={failingId === session.id}
                  class="inline-flex items-center rounded-md border border-transparent bg-danger px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-danger focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {#if failingId === session.id}
                    {m.admin_settings_uploads_force_fail_pending()}
                  {:else}
                    {m.admin_settings_uploads_force_fail_button()}
                  {/if}
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<!-- Force-fail confirmation modal -->
{#if confirmSession}
  <div
    class="fixed inset-0 z-50 overflow-y-auto"
    aria-labelledby="upload-force-fail-modal-title"
    role="dialog"
    aria-modal="true"
  >
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        class="fixed inset-0 bg-stone-500 bg-opacity-75 transition-opacity"
        aria-hidden="true"
        onclick={() => (confirmSession = null)}
      ></div>

      <!-- Center modal -->
      <span class="hidden sm:inline-block sm:h-screen sm:align-middle" aria-hidden="true">&#8203;</span>

      <!-- Modal panel -->
      <div class="inline-block transform overflow-hidden rounded-lg bg-surface-card text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle">
        <div class="bg-surface-card px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <h3 class="text-lg font-medium leading-6 text-stone-900" id="upload-force-fail-modal-title">
            {m.admin_settings_uploads_force_fail_button()}
          </h3>
          <div class="mt-2">
            <p class="text-sm text-stone-500">
              {m.admin_settings_uploads_force_fail_confirm({ id: shortId(confirmSession.id) })}
            </p>
          </div>
        </div>
        <div class="bg-stone-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={handleConfirmForceFail}
            class="inline-flex w-full justify-center rounded-md bg-danger px-4 py-2 text-base font-medium text-white shadow-sm hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-danger focus:ring-offset-2 sm:ml-3 sm:w-auto sm:text-sm"
          >
            {m.admin_settings_uploads_force_fail_button()}
          </button>
          <button
            type="button"
            onclick={() => (confirmSession = null)}
            class="mt-3 inline-flex w-full justify-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-base font-medium text-stone-700 shadow-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
          >
            {m.admin_settings_taxon_cancel()}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
