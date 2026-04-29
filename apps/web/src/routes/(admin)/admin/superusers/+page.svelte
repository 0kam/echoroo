<script lang="ts">
  /**
   * Admin — Superusers management page (Phase 15 / FR-111 T955).
   *
   * Surfaces the `superusers` table, lets active superusers open M-of-N
   * approval tickets to add or revoke peers, and links out to the IP
   * allowlist editor.
   *
   * Programmatic API key callers cannot reach this page (FR-084) — the
   * cookie session is mandatory.
   */

  import { goto } from '$app/navigation';
  import { ApiError } from '$lib/api/client';
  import {
    superuserApi,
    type SuperuserListResponse,
    type SuperuserSummary,
  } from '$lib/api/superusers';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';

  let listing = $state<SuperuserListResponse | null>(null);
  let isLoading = $state(true);
  let error = $state<string | null>(null);
  let banner = $state<string | null>(null);

  // Add modal state
  let showAddModal = $state(false);
  let addTargetUserId = $state('');
  let addAllowedCidrs = $state('');
  let addError = $state<string | null>(null);
  let isSubmittingAdd = $state(false);

  // Revoke confirmation state
  let revokeTarget = $state<SuperuserSummary | null>(null);
  let revokeError = $state<string | null>(null);

  async function load() {
    isLoading = true;
    error = null;
    try {
      listing = await superuserApi.list();
    } catch (err) {
      error = mapError(err, m.admin_superusers_error_load());
    } finally {
      isLoading = false;
    }
  }

  $effect(() => {
    load();
  });

  function mapError(err: unknown, fallback: string): string {
    if (err instanceof ApiError) {
      // Universal API key veto (FR-084) — defensive, should never fire
      // through cookie sessions.
      if (
        err.code === 'ERR_API_KEY_FORBIDDEN' ||
        err.code === 'ERR_SUPERUSER_API_KEY_FORBIDDEN'
      ) {
        return m.admin_superusers_api_key_forbidden();
      }
      if (err.code === 'ERR_LAST_SUPERUSER_PROTECTION') {
        return m.admin_superusers_last_protection_error();
      }
      if (err.code === 'stale_add_ticket_target_already_superuser') {
        return m.admin_superusers_stale_add_ticket();
      }
      return err.detail || err.message || fallback;
    }
    if (err instanceof Error) return err.message;
    return fallback;
  }

  function formatDate(dateString: string | null): string {
    if (!dateString) return '-';
    return new Date(dateString).toLocaleString(getLocale());
  }

  function parseCidrLines(raw: string): string[] {
    return raw
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  }

  function openAddModal() {
    addTargetUserId = '';
    addAllowedCidrs = '';
    addError = null;
    showAddModal = true;
  }

  function closeAddModal() {
    if (isSubmittingAdd) return;
    showAddModal = false;
  }

  async function handleAdd(e: Event) {
    e.preventDefault();
    if (!addTargetUserId.trim()) {
      addError = m.admin_superusers_add_missing_user_id();
      return;
    }
    isSubmittingAdd = true;
    addError = null;
    try {
      const cidrs = parseCidrLines(addAllowedCidrs);
      const result = await superuserApi.add({
        target_user_id: addTargetUserId.trim(),
        ...(cidrs.length > 0 ? { allowed_ip_cidrs: cidrs } : {}),
      });
      showAddModal = false;
      banner =
        result.status === 'pending'
          ? m.admin_superusers_add_pending_banner({
              ticket: result.approval_request_id ?? '',
            })
          : m.admin_superusers_add_direct_banner();
      await load();
    } catch (err) {
      addError = mapError(err, m.admin_superusers_add_failed());
    } finally {
      isSubmittingAdd = false;
    }
  }

  async function confirmRevoke() {
    if (!revokeTarget) return;
    revokeError = null;
    try {
      const result = await superuserApi.revoke(revokeTarget.id);
      banner = m.admin_superusers_revoke_pending_banner({
        ticket: result.approval_request_id ?? '',
      });
      revokeTarget = null;
      await load();
    } catch (err) {
      revokeError = mapError(err, m.admin_superusers_revoke_failed());
    }
  }

  function cancelRevoke() {
    revokeTarget = null;
    revokeError = null;
  }
</script>

<svelte:head>
  <title>{m.admin_superusers_heading()} - Admin - Echoroo</title>
</svelte:head>

<div class="px-2 py-2">
  <!-- Header -->
  <div class="mb-6 flex items-start justify-between">
    <div>
      <h1 class="text-3xl font-bold text-stone-900 dark:text-stone-100">
        {m.admin_superusers_heading()}
      </h1>
      <p class="mt-2 text-sm text-stone-600 dark:text-stone-400">
        {m.admin_superusers_description()}
      </p>
    </div>
    <div class="flex gap-2">
      <a
        href={localizeHref('/admin/superusers/approvals')}
        class="rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 dark:border-stone-700 dark:text-stone-200 dark:hover:bg-stone-800"
      >
        {m.admin_superusers_link_approvals()}
      </a>
      <a
        href={localizeHref('/admin/superusers/break-glass')}
        class="rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 dark:border-stone-700 dark:text-stone-200 dark:hover:bg-stone-800"
      >
        {m.admin_superusers_link_break_glass()}
      </a>
      <button
        type="button"
        onclick={openAddModal}
        class="rounded-md bg-primary-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700"
      >
        {m.admin_superusers_add_button()}
      </button>
    </div>
  </div>

  {#if banner}
    <div
      class="mb-4 rounded-md border border-success/30 bg-success-light p-3 text-sm text-success"
      role="status"
    >
      {banner}
    </div>
  {/if}

  {#if error}
    <div
      class="mb-4 rounded-md border border-danger/30 bg-danger-light p-3 text-sm text-danger"
      role="alert"
    >
      {error}
    </div>
  {/if}

  {#if isLoading}
    <div class="flex items-center justify-center py-12">
      <span class="text-sm text-stone-500">{m.common_loading()}</span>
    </div>
  {:else if listing}
    <!-- Counts banner -->
    <div
      class="mb-4 grid grid-cols-1 gap-3 rounded-md border border-card bg-surface-card p-4 sm:grid-cols-3"
    >
      <div>
        <div class="text-xs uppercase text-stone-500 dark:text-stone-400">
          {m.admin_superusers_count_active()}
        </div>
        <div class="text-xl font-semibold text-stone-900 dark:text-stone-100">
          {listing.active_count}
        </div>
      </div>
      <div>
        <div class="text-xs uppercase text-stone-500 dark:text-stone-400">
          {m.admin_superusers_count_minimum()}
        </div>
        <div class="text-xl font-semibold text-stone-900 dark:text-stone-100">
          {listing.min_superusers}
        </div>
      </div>
      <div>
        <div class="text-xs uppercase text-stone-500 dark:text-stone-400">
          {m.admin_superusers_count_break_glass()}
        </div>
        <div
          class="text-xl font-semibold {listing.break_glass_active
            ? 'text-danger'
            : 'text-stone-900 dark:text-stone-100'}"
        >
          {listing.break_glass_active
            ? m.admin_superusers_count_break_glass_yes()
            : m.admin_superusers_count_break_glass_no()}
        </div>
      </div>
    </div>

    <!-- Table -->
    <div class="overflow-hidden rounded-lg border border-card bg-surface-card shadow-sm">
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-stone-200 dark:divide-stone-700">
          <thead class="bg-stone-50 dark:bg-stone-800">
            <tr>
              <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-stone-500">
                {m.admin_superusers_table_user_id()}
              </th>
              <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-stone-500">
                {m.admin_superusers_table_added_at()}
              </th>
              <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-stone-500">
                {m.admin_superusers_table_revoked_at()}
              </th>
              <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-stone-500">
                {m.admin_superusers_table_cidrs()}
              </th>
              <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-stone-500">
                {m.admin_superusers_table_keys()}
              </th>
              <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-stone-500">
                {m.admin_superusers_table_actions()}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-stone-200 bg-surface-card dark:divide-stone-700">
            {#each listing.items as row (row.id)}
              <tr class:opacity-60={row.revoked_at !== null}>
                <td class="px-4 py-2 font-mono text-xs text-stone-900 dark:text-stone-100">
                  {row.user_id}
                </td>
                <td class="whitespace-nowrap px-4 py-2 text-xs text-stone-600 dark:text-stone-400">
                  {formatDate(row.added_at)}
                </td>
                <td class="whitespace-nowrap px-4 py-2 text-xs text-stone-600 dark:text-stone-400">
                  {row.revoked_at ? formatDate(row.revoked_at) : '-'}
                </td>
                <td class="px-4 py-2 text-xs text-stone-700 dark:text-stone-300">
                  {#if row.allowed_ip_cidrs.length === 0}
                    <span class="text-stone-400">-</span>
                  {:else}
                    <ul class="m-0 list-none p-0">
                      {#each row.allowed_ip_cidrs as cidr}
                        <li class="font-mono">{cidr}</li>
                      {/each}
                    </ul>
                  {/if}
                </td>
                <td class="px-4 py-2 text-center text-xs text-stone-700 dark:text-stone-300">
                  {row.webauthn_credential_count}
                </td>
                <td class="whitespace-nowrap px-4 py-2 text-xs">
                  <div class="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onclick={() => goto(localizeHref(`/admin/superusers/${row.id}/ip-allowlist`))}
                      class="rounded bg-stone-100 px-2 py-1 text-xs font-medium text-stone-700 transition-colors hover:bg-stone-200 dark:bg-stone-700 dark:text-stone-200 dark:hover:bg-stone-600"
                    >
                      {m.admin_superusers_action_edit_cidrs()}
                    </button>
                    {#if row.revoked_at === null}
                      <button
                        type="button"
                        onclick={() => {
                          revokeTarget = row;
                          revokeError = null;
                        }}
                        class="rounded bg-danger-light px-2 py-1 text-xs font-medium text-danger transition-colors hover:bg-danger/20"
                      >
                        {m.admin_superusers_action_revoke()}
                      </button>
                    {/if}
                  </div>
                </td>
              </tr>
            {/each}
            {#if listing.items.length === 0}
              <tr>
                <td colspan="6" class="px-4 py-6 text-center text-sm text-stone-500">
                  {m.admin_superusers_empty()}
                </td>
              </tr>
            {/if}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
</div>

<!-- Add modal -->
{#if showAddModal}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="add-superuser-title"
  >
    <div class="w-full max-w-md rounded-lg bg-surface-card shadow-xl">
      <div class="border-b border-stone-200 px-6 py-4 dark:border-stone-700">
        <h2 id="add-superuser-title" class="m-0 text-lg font-semibold">
          {m.admin_superusers_add_modal_title()}
        </h2>
      </div>
      <form onsubmit={handleAdd}>
        <div class="space-y-4 p-6">
          <p class="m-0 text-xs text-stone-600 dark:text-stone-400">
            {m.admin_superusers_add_modal_description()}
          </p>
          <div>
            <label
              for="add-target-user-id"
              class="mb-1 block text-xs font-medium text-stone-700 dark:text-stone-300"
            >
              {m.admin_superusers_add_target_user_id_label()}
            </label>
            <input
              id="add-target-user-id"
              type="text"
              bind:value={addTargetUserId}
              required
              placeholder="00000000-0000-0000-0000-000000000000"
              class="block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 font-mono text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>
          <div>
            <label
              for="add-allowed-cidrs"
              class="mb-1 block text-xs font-medium text-stone-700 dark:text-stone-300"
            >
              {m.admin_superusers_add_allowed_cidrs_label()}
            </label>
            <textarea
              id="add-allowed-cidrs"
              bind:value={addAllowedCidrs}
              rows="4"
              placeholder="10.0.0.0/8&#10;192.168.1.0/24"
              class="block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 font-mono text-xs focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            ></textarea>
            <p class="mt-1 text-xs text-stone-500">
              {m.admin_superusers_add_allowed_cidrs_hint()}
            </p>
          </div>
          {#if addError}
            <div
              class="rounded-md border border-danger/30 bg-danger-light p-2 text-xs text-danger"
              role="alert"
            >
              {addError}
            </div>
          {/if}
        </div>
        <div class="flex justify-end gap-3 border-t border-stone-200 px-6 py-4 dark:border-stone-700">
          <button
            type="button"
            onclick={closeAddModal}
            disabled={isSubmittingAdd}
            class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {m.common_cancel()}
          </button>
          <button
            type="submit"
            disabled={isSubmittingAdd}
            class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isSubmittingAdd ? m.common_processing() : m.admin_superusers_add_submit()}
          </button>
        </div>
      </form>
    </div>
  </div>
{/if}

<!-- Revoke confirm -->
<ConfirmDialog
  isOpen={revokeTarget !== null}
  title={m.admin_superusers_revoke_confirm_title()}
  message={m.admin_superusers_revoke_confirm_message({
    user_id: revokeTarget?.user_id ?? '',
  })}
  confirmText={m.admin_superusers_action_revoke()}
  cancelText={m.common_cancel()}
  isDanger={true}
  warningItems={[m.admin_superusers_revoke_warning_mof_n()]}
  errorMessage={revokeError}
  onConfirm={confirmRevoke}
  onCancel={cancelRevoke}
/>
