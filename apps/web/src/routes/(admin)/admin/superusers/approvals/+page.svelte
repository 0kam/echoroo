<script lang="ts">
  /**
   * Admin — Superuser approval queue (Phase 15 / FR-111 T955).
   *
   * Lists every M-of-N approval ticket (defaults to pending) with
   * approve / reject actions.  Quorum is enforced server-side; the UI
   * simply displays the current approval count and reports the resulting
   * status.
   */

  import { ApiError } from '$lib/api/client';
  import {
    superuserApi,
    type SuperuserApprovalRequestListResponse,
    type SuperuserApprovalRequestSummary,
  } from '$lib/api/superusers';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import WebAuthnGatePrompt from '$lib/components/admin/WebAuthnGatePrompt.svelte';
  import { focusTrap } from '$lib/actions/focusTrap';

  type StatusFilter = 'pending' | 'applied' | 'rejected' | 'all';

  let statusFilter = $state<StatusFilter>('pending');
  let listing = $state<SuperuserApprovalRequestListResponse | null>(null);
  let isLoading = $state(true);
  let error = $state<string | null>(null);
  let banner = $state<string | null>(null);

  let rejectTarget = $state<SuperuserApprovalRequestSummary | null>(null);
  let rejectReason = $state('');
  let rejectError = $state<string | null>(null);
  let isSubmittingReject = $state(false);

  // WebAuthn step-up gate (FR-111).
  let gateOpen = $state(false);
  let pendingAction = $state<(() => Promise<void>) | null>(null);
  let gateContextLabel = $state<'approve' | 'reject' | null>(null);

  async function load() {
    isLoading = true;
    error = null;
    try {
      const filter = statusFilter === 'all' ? undefined : statusFilter;
      listing = await superuserApi.listApprovalRequests(filter);
    } catch (err) {
      error = mapError(err, m.admin_superusers_approvals_error_load());
    } finally {
      isLoading = false;
    }
  }

  $effect(() => {
    // Reference statusFilter so the effect re-runs whenever the filter
    // changes; the value itself is consumed inside ``load()``.
    void statusFilter;
    load();
  });

  function mapError(err: unknown, fallback: string): string {
    if (err instanceof ApiError) {
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

  function formatDate(s: string | null): string {
    if (!s) return '-';
    return new Date(s).toLocaleString(getLocale());
  }

  function handleApprove(ticket: SuperuserApprovalRequestSummary) {
    // FR-111: gate every approve through WebAuthn before the API call.
    error = null;
    banner = null;
    pendingAction = async () => {
      try {
        const result = await superuserApi.approve(ticket.id);
        if (result.status === 'applied') {
          banner = m.admin_superusers_approvals_quorum_reached();
        } else {
          banner = m.admin_superusers_approvals_one_more_needed();
        }
        await load();
      } catch (err) {
        error = mapError(err, m.admin_superusers_approvals_approve_failed());
      }
    };
    gateContextLabel = 'approve';
    gateOpen = true;
  }

  function openReject(ticket: SuperuserApprovalRequestSummary) {
    rejectTarget = ticket;
    rejectReason = '';
    rejectError = null;
  }

  function cancelReject() {
    if (isSubmittingReject) return;
    rejectTarget = null;
    rejectReason = '';
    rejectError = null;
  }

  function confirmReject() {
    if (!rejectTarget) return;
    if (!rejectReason.trim()) {
      rejectError = m.admin_superusers_approvals_reject_reason_required();
      return;
    }
    rejectError = null;
    const target = rejectTarget;
    const reason = rejectReason.trim();
    pendingAction = async () => {
      isSubmittingReject = true;
      try {
        await superuserApi.reject(target.id, reason);
        banner = m.admin_superusers_approvals_rejected();
        rejectTarget = null;
        rejectReason = '';
        await load();
      } catch (err) {
        rejectError = mapError(err, m.admin_superusers_approvals_reject_failed());
      } finally {
        isSubmittingReject = false;
      }
    };
    gateContextLabel = 'reject';
    gateOpen = true;
  }

  function handleGateSuccess() {
    pendingAction = null;
    gateContextLabel = null;
  }

  function handleGateCancel() {
    pendingAction = null;
    if (gateContextLabel === 'approve') {
      error = m.admin_superusers_webauthn_gate_cancelled();
    } else if (gateContextLabel === 'reject') {
      rejectError = m.admin_superusers_webauthn_gate_cancelled();
    }
    gateContextLabel = null;
  }

  function handleGateError(message: string) {
    pendingAction = null;
    if (gateContextLabel === 'approve') {
      error = message;
    } else if (gateContextLabel === 'reject') {
      rejectError = message;
    }
    gateContextLabel = null;
  }

  /**
   * Render the redacted detail object (backend strips sensitive keys).
   * We display each remaining key/value pair as `key: value` with JSON
   * stringification for nested values.
   */
  function renderDetail(detail: Record<string, unknown> | null): string {
    if (!detail) return '-';
    const parts: string[] = [];
    for (const [key, value] of Object.entries(detail)) {
      if (typeof value === 'string') {
        parts.push(`${key}: ${value}`);
      } else {
        try {
          parts.push(`${key}: ${JSON.stringify(value)}`);
        } catch {
          parts.push(`${key}: [unserialisable]`);
        }
      }
    }
    return parts.length === 0 ? '-' : parts.join('  |  ');
  }
</script>

<svelte:head>
  <title>{m.admin_superusers_approvals_heading()} - Admin - Echoroo</title>
</svelte:head>

<div class="px-2 py-2">
  <div class="mb-6 flex items-start justify-between">
    <div>
      <h1 class="text-3xl font-bold text-stone-900 dark:text-stone-100">
        {m.admin_superusers_approvals_heading()}
      </h1>
      <p class="mt-2 text-sm text-stone-600 dark:text-stone-400">
        {m.admin_superusers_approvals_description()}
      </p>
    </div>
    <a
      href={localizeHref('/admin/superusers')}
      class="rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 dark:border-stone-700 dark:text-stone-200 dark:hover:bg-stone-800"
    >
      {m.admin_superusers_approvals_back_to_list()}
    </a>
  </div>

  <div class="mb-4 flex items-center gap-2">
    <label for="status-filter" class="text-xs font-medium text-stone-600 dark:text-stone-400">
      {m.admin_superusers_approvals_filter_label()}
    </label>
    <select
      id="status-filter"
      bind:value={statusFilter}
      class="rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
    >
      <option value="pending">{m.admin_superusers_approvals_filter_pending()}</option>
      <option value="applied">{m.admin_superusers_approvals_filter_applied()}</option>
      <option value="rejected">{m.admin_superusers_approvals_filter_rejected()}</option>
      <option value="all">{m.admin_superusers_approvals_filter_all()}</option>
    </select>
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
    <div class="py-12 text-center text-sm text-stone-500">{m.common_loading()}</div>
  {:else if listing}
    <div
      class="mb-4 grid grid-cols-1 gap-3 rounded-md border border-card bg-surface-card p-4 sm:grid-cols-2"
    >
      <div>
        <div class="text-xs uppercase text-stone-500 dark:text-stone-400">
          {m.admin_superusers_approvals_pending_count()}
        </div>
        <div class="text-xl font-semibold">{listing.pending_count}</div>
      </div>
      <div>
        <div class="text-xs uppercase text-stone-500 dark:text-stone-400">
          {m.admin_superusers_approvals_min_approvals()}
        </div>
        <div class="text-xl font-semibold">{listing.min_approvals}</div>
      </div>
    </div>

    <div class="space-y-3">
      {#each listing.items as ticket (ticket.id)}
        <div class="rounded-md border border-card bg-surface-card p-4 shadow-sm">
          <div class="mb-2 flex items-start justify-between gap-3">
            <div>
              <div class="text-sm font-semibold">
                {ticket.action}
              </div>
              <div class="text-xs text-stone-500">
                <span class="font-mono">{ticket.id}</span>
              </div>
            </div>
            <span
              class="rounded-full px-2 py-0.5 text-xs font-medium {ticket.status === 'pending'
                ? 'bg-warning-light text-warning'
                : ticket.status === 'applied'
                  ? 'bg-success-light text-success'
                  : 'bg-danger-light text-danger'}"
            >
              {ticket.status}
            </span>
          </div>

          <div class="grid grid-cols-1 gap-3 text-xs sm:grid-cols-2">
            <div>
              <span class="text-stone-500">
                {m.admin_superusers_approvals_field_requested_by()}:
              </span>
              <span class="font-mono">{ticket.requested_by_id}</span>
            </div>
            <div>
              <span class="text-stone-500">
                {m.admin_superusers_approvals_field_created_at()}:
              </span>
              {formatDate(ticket.created_at)}
            </div>
            <div>
              <span class="text-stone-500">
                {m.admin_superusers_approvals_field_approvals()}:
              </span>
              {ticket.approvals.length} / {listing.min_approvals}
            </div>
            <div>
              <span class="text-stone-500">
                {m.admin_superusers_approvals_field_executed_at()}:
              </span>
              {formatDate(ticket.executed_at)}
            </div>
          </div>

          <div class="mt-3 rounded-md bg-stone-50 p-2 text-xs text-stone-700 dark:bg-stone-800 dark:text-stone-300">
            <span class="text-stone-500">
              {m.admin_superusers_approvals_field_detail()}:
            </span>
            <span class="ml-1 font-mono">{renderDetail(ticket.detail)}</span>
          </div>

          {#if ticket.status === 'pending'}
            <div class="mt-3 flex gap-2">
              <button
                type="button"
                onclick={() => handleApprove(ticket)}
                class="rounded-md bg-success px-3 py-1.5 text-xs font-medium text-white transition-colors hover:opacity-90"
              >
                {m.admin_superusers_approvals_approve_button()}
              </button>
              <button
                type="button"
                onclick={() => openReject(ticket)}
                class="rounded-md bg-danger px-3 py-1.5 text-xs font-medium text-white transition-colors hover:opacity-90"
              >
                {m.admin_superusers_approvals_reject_button()}
              </button>
            </div>
          {/if}
        </div>
      {/each}

      {#if listing.items.length === 0}
        <div
          class="rounded-lg border-2 border-dashed border-stone-300 p-8 text-center text-sm text-stone-500"
        >
          {m.admin_superusers_approvals_empty()}
        </div>
      {/if}
    </div>
  {/if}
</div>

<!-- Reject reason dialog -->
{#if rejectTarget}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="reject-title"
  >
    <div
      use:focusTrap={{ onClose: cancelReject }}
      class="w-full max-w-md rounded-lg bg-surface-card shadow-xl"
    >
      <div class="border-b border-stone-200 px-6 py-4 dark:border-stone-700">
        <h2 id="reject-title" class="m-0 text-lg font-semibold">
          {m.admin_superusers_approvals_reject_title()}
        </h2>
      </div>
      <div class="space-y-3 p-6">
        <p class="m-0 text-xs text-stone-600 dark:text-stone-400">
          {m.admin_superusers_approvals_reject_description()}
        </p>
        <div>
          <label
            for="reject-reason"
            class="mb-1 block text-xs font-medium text-stone-700 dark:text-stone-300"
          >
            {m.admin_superusers_approvals_reject_reason_label()}
          </label>
          <textarea
            id="reject-reason"
            bind:value={rejectReason}
            rows="4"
            required
            maxlength="2000"
            class="block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          ></textarea>
        </div>
        {#if rejectError}
          <div
            class="rounded-md border border-danger/30 bg-danger-light p-2 text-xs text-danger"
            role="alert"
          >
            {rejectError}
          </div>
        {/if}
      </div>
      <div class="flex justify-end gap-3 border-t border-stone-200 px-6 py-4 dark:border-stone-700">
        <button
          type="button"
          onclick={cancelReject}
          disabled={isSubmittingReject}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.common_cancel()}
        </button>
        <button
          type="button"
          onclick={confirmReject}
          disabled={isSubmittingReject}
          class="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmittingReject ? m.common_processing() : m.admin_superusers_approvals_reject_submit()}
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- WebAuthn step-up gate (FR-111) -->
<WebAuthnGatePrompt
  bind:isOpen={gateOpen}
  action={pendingAction}
  onSuccess={handleGateSuccess}
  onCancel={handleGateCancel}
  onError={handleGateError}
/>

