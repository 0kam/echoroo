<script lang="ts">
  /**
   * Bulk member-invitation form + one-shot result table (T280 / T281).
   *
   * Presentational shell: the parent owns the submit handler, the loading
   * flag and the transient `results` list (one-shot URLs, never persisted).
   * This component binds the textarea / role fields, renders the result
   * table and owns the ephemeral "copied" flag for the CSV export.
   */
  import type { BulkInvitationResultItem, MemberInvitationRole } from '$lib/types';
  import { buildInviteUrl } from '$lib/api/projects';
  import {
    getBulkInvitationStatusLabel,
    getBulkInvitationStatusBadgeClass,
  } from '$lib/utils/statusFormatters';
  import * as m from '$lib/paraglide/messages';
  import { buildBulkCsv } from './csv';

  interface Props {
    emailsText: string;
    role: MemberInvitationRole;
    isSubmitting: boolean;
    submitError: string | null;
    /** One-shot result rows (T281), or null before the first submit. */
    results: BulkInvitationResultItem[] | null;
    onSubmit: (e: Event) => void;
  }

  let {
    emailsText = $bindable(),
    role = $bindable(),
    isSubmitting,
    submitError,
    results,
    onSubmit,
  }: Props = $props();

  // Ephemeral "Copied!" feedback for the CSV export button.
  let csvCopied = $state(false);

  /**
   * Localized label for a bulk result status.
   */
  function bulkStatusLabel(status: BulkInvitationResultItem['status']): string {
    return getBulkInvitationStatusLabel(status, {
      issued: m.collaborators_bulk_status_issued,
      duplicate_pending: m.collaborators_bulk_status_duplicate_pending,
      already_member: m.collaborators_bulk_status_already_member,
      rate_limited: m.collaborators_bulk_status_rate_limited,
      internal_error: m.collaborators_bulk_status_internal_error,
    });
  }

  /**
   * Badge classes for a bulk result status.
   */
  function bulkStatusBadgeClass(status: BulkInvitationResultItem['status']): string {
    return getBulkInvitationStatusBadgeClass(status);
  }

  /**
   * Copy the bulk results as CSV (`email,status,invitation_url`). One-shot
   * URLs are copied to the clipboard only — never persisted by this app.
   */
  function copyBulkCsv() {
    if (!results) return;

    const csv = buildBulkCsv(results, buildInviteUrl);

    navigator.clipboard
      .writeText(csv)
      .then(() => {
        csvCopied = true;
        setTimeout(() => {
          csvCopied = false;
        }, 2000);
      })
      .catch((err) => console.error('Failed to copy CSV:', err));
  }
</script>

<h2 class="mb-4 text-lg font-semibold text-stone-900">
  {m.collaborators_bulk_heading()}
</h2>
<form onsubmit={onSubmit} class="space-y-4">
  <div>
    <label for="bulk-emails" class="block text-sm font-medium text-stone-700">
      {m.collaborators_bulk_emails_label()}
    </label>
    <textarea
      id="bulk-emails"
      rows="6"
      bind:value={emailsText}
      disabled={isSubmitting}
      class="mt-1 block w-full resize-y rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100"
      placeholder={m.collaborators_bulk_emails_placeholder()}
    ></textarea>
    <p class="mt-1 text-xs text-stone-500">{m.collaborators_bulk_emails_help()}</p>
  </div>

  <div class="flex items-end space-x-4">
    <div class="w-48">
      <label for="bulk-role" class="block text-sm font-medium text-stone-700">
        {m.collaborators_role_label()}
      </label>
      <select
        id="bulk-role"
        bind:value={role}
        disabled={isSubmitting}
        class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100"
      >
        <option value="viewer">{m.role_viewer()}</option>
        <option value="member">{m.role_member()}</option>
        <option value="admin">{m.role_admin()}</option>
      </select>
    </div>

    <button
      type="submit"
      disabled={isSubmitting}
      class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
    >
      {isSubmitting
        ? m.collaborators_bulk_submitting()
        : m.collaborators_bulk_submit_button()}
    </button>
  </div>

  {#if submitError}
    <p class="text-sm text-danger">{submitError}</p>
  {/if}
</form>

{#if results}
  <!-- Bulk results (T280) with one-shot URLs (T281) -->
  <div class="mt-6">
    <div class="mb-3 flex items-center justify-between">
      <h3 class="text-base font-semibold text-stone-900">
        {m.collaborators_bulk_results_heading()}
      </h3>
      <button
        type="button"
        onclick={copyBulkCsv}
        class="rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50"
      >
        {csvCopied ? m.collaborators_bulk_copied_csv() : m.collaborators_bulk_copy_csv()}
      </button>
    </div>

    <!-- Non-recoverability warning -->
    <div class="mb-4 rounded-md bg-warning-light p-4">
      <div class="flex">
        <svg
          class="h-5 w-5 flex-shrink-0 text-warning"
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path
            fill-rule="evenodd"
            d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
            clip-rule="evenodd"
          />
        </svg>
        <div class="ml-3">
          <p class="text-sm font-medium text-warning">
            {m.collaborators_bulk_results_warning()}
          </p>
        </div>
      </div>
    </div>

    <div class="overflow-x-auto">
      <table class="w-full text-left">
        <thead>
          <tr class="border-b border-stone-200 bg-stone-50">
            <th class="px-4 py-2 text-sm font-medium text-stone-700"
              >{m.collaborators_bulk_col_email()}</th
            >
            <th class="px-4 py-2 text-sm font-medium text-stone-700"
              >{m.collaborators_bulk_col_status()}</th
            >
            <th class="px-4 py-2 text-sm font-medium text-stone-700"
              >{m.collaborators_bulk_col_url()}</th
            >
          </tr>
        </thead>
        <tbody>
          {#each results as result, i (i)}
            <tr class="border-b border-stone-200">
              <td class="px-4 py-2 text-sm text-stone-700">{result.email}</td>
              <td class="px-4 py-2 text-sm">
                <span
                  class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium {bulkStatusBadgeClass(
                    result.status
                  )}"
                >
                  {bulkStatusLabel(result.status)}
                </span>
              </td>
              <td class="px-4 py-2 text-sm text-stone-700">
                {#if result.invitation_url}
                  <input
                    type="text"
                    value={buildInviteUrl(result.invitation_url)}
                    readonly
                    class="w-full rounded-md border border-stone-300 bg-stone-50 px-3 py-2 font-mono text-sm"
                  />
                {:else}
                  <span class="text-stone-500">{result.error_message ?? '—'}</span>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>
{/if}
