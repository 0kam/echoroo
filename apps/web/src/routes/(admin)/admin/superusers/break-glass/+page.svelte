<script lang="ts">
  /**
   * Admin — Break-glass control panel (Phase 15 / FR-111 T955).
   *
   * Surfaces the current 72-hour break-glass mode state and lets the
   * remaining superuser activate it when the platform is down to one
   * active row.  Displays a live countdown so operators know how long
   * they have until the window auto-closes.
   *
   * IMPORTANT (FR-111): break-glass is for emergencies only.  The UI
   * surfaces a prominent warning message before enable.
   */

  import { ApiError } from '$lib/api/client';
  import {
    superuserApi,
    type SuperuserBreakGlassStatusResponse,
  } from '$lib/api/superusers';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import WebAuthnGatePrompt from '$lib/components/admin/WebAuthnGatePrompt.svelte';

  let status = $state<SuperuserBreakGlassStatusResponse | null>(null);
  let isLoading = $state(true);
  let error = $state<string | null>(null);
  let banner = $state<string | null>(null);
  let now = $state(Date.now());
  let reason = $state('');
  let isSubmitting = $state(false);
  let confirmed = $state(false);

  // WebAuthn step-up gate (FR-111).
  let gateOpen = $state(false);
  let pendingAction = $state<(() => Promise<void>) | null>(null);

  async function load() {
    isLoading = true;
    error = null;
    try {
      status = await superuserApi.breakGlassStatus();
    } catch (err) {
      error = mapError(err, m.admin_superusers_break_glass_error_load());
    } finally {
      isLoading = false;
    }
  }

  $effect(() => {
    load();
    // Live timer for countdown.
    const interval = setInterval(() => {
      now = Date.now();
    }, 30_000);
    return () => clearInterval(interval);
  });

  function mapError(err: unknown, fallback: string): string {
    if (err instanceof ApiError) {
      if (
        err.code === 'ERR_API_KEY_FORBIDDEN' ||
        err.code === 'ERR_SUPERUSER_API_KEY_FORBIDDEN'
      ) {
        return m.admin_superusers_api_key_forbidden();
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

  function remaining(target: string | null): string {
    if (!target) return '-';
    const ms = new Date(target).getTime() - now;
    if (ms <= 0) return m.admin_superusers_break_glass_expired();
    const totalMinutes = Math.floor(ms / 60_000);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return m.admin_superusers_break_glass_remaining({
      hours,
      minutes,
    });
  }

  function handleEnter(e: Event) {
    e.preventDefault();
    if (!reason.trim()) {
      error = m.admin_superusers_break_glass_reason_required();
      return;
    }
    if (!confirmed) {
      error = m.admin_superusers_break_glass_confirm_required();
      return;
    }
    error = null;
    banner = null;
    // FR-111: gate the destructive enter call through WebAuthn.
    const submittedReason = reason.trim();
    pendingAction = async () => {
      isSubmitting = true;
      try {
        status = await superuserApi.enterBreakGlass(submittedReason);
        banner = m.admin_superusers_break_glass_entered();
        reason = '';
        confirmed = false;
      } catch (err) {
        error = mapError(err, m.admin_superusers_break_glass_enter_failed());
      } finally {
        isSubmitting = false;
      }
    };
    gateOpen = true;
  }

  function handleGateSuccess() {
    pendingAction = null;
  }

  function handleGateCancel() {
    pendingAction = null;
    error = m.admin_superusers_webauthn_gate_cancelled();
  }

  function handleGateError(message: string) {
    pendingAction = null;
    error = message;
  }
</script>

<svelte:head>
  <title>{m.admin_superusers_break_glass_heading()} - Admin - Echoroo</title>
</svelte:head>

<div class="px-2 py-2">
  <div class="mb-6 flex items-start justify-between">
    <div>
      <h1 class="text-3xl font-bold text-stone-900 dark:text-stone-100">
        {m.admin_superusers_break_glass_heading()}
      </h1>
      <p class="mt-2 text-sm text-stone-600 dark:text-stone-400">
        {m.admin_superusers_break_glass_description()}
      </p>
    </div>
    <a
      href={localizeHref('/admin/superusers')}
      class="rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 dark:border-stone-700 dark:text-stone-200 dark:hover:bg-stone-800"
    >
      {m.admin_superusers_approvals_back_to_list()}
    </a>
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
  {:else if status?.active}
    <!-- Active state -->
    <div
      class="rounded-md border border-danger/40 bg-danger-light p-4 text-sm text-danger"
      role="alert"
    >
      <div class="mb-2 text-base font-semibold">
        {m.admin_superusers_break_glass_active_warning()}
      </div>
      <dl class="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
        <div>
          <dt class="opacity-75">
            {m.admin_superusers_break_glass_field_started_at()}
          </dt>
          <dd class="font-mono">{formatDate(status.started_at)}</dd>
        </div>
        <div>
          <dt class="opacity-75">
            {m.admin_superusers_break_glass_field_expires_at()}
          </dt>
          <dd class="font-mono">{formatDate(status.expires_at)}</dd>
        </div>
        <div>
          <dt class="opacity-75">
            {m.admin_superusers_break_glass_field_remaining()}
          </dt>
          <dd class="font-mono">{remaining(status.expires_at)}</dd>
        </div>
        <div>
          <dt class="opacity-75">
            {m.admin_superusers_break_glass_field_replacement_deadline()}
          </dt>
          <dd class="font-mono">{formatDate(status.replacement_deadline_at)}</dd>
        </div>
        <div class="sm:col-span-2">
          <dt class="opacity-75">
            {m.admin_superusers_break_glass_field_reason()}
          </dt>
          <dd class="break-words">{status.reason ?? '-'}</dd>
        </div>
      </dl>
      <p class="mt-3 m-0 text-xs">
        {m.admin_superusers_break_glass_replacement_reminder()}
      </p>
    </div>
  {:else}
    <!-- Inactive state — enter form -->
    <div class="rounded-md border border-card bg-surface-card p-4">
      <h2 class="m-0 mb-2 text-lg font-semibold text-stone-900 dark:text-stone-100">
        {m.admin_superusers_break_glass_inactive_heading()}
      </h2>
      <p class="m-0 mb-4 text-sm text-stone-600 dark:text-stone-400">
        {m.admin_superusers_break_glass_inactive_description()}
      </p>
      <div
        class="mb-4 rounded-md border border-warning/30 bg-warning-light p-3 text-xs text-warning"
        role="alert"
      >
        {m.admin_superusers_break_glass_warning_emergency_only()}
      </div>
      <form onsubmit={handleEnter} class="space-y-4">
        <div>
          <label
            for="break-glass-reason"
            class="mb-1 block text-xs font-medium text-stone-700 dark:text-stone-300"
          >
            {m.admin_superusers_break_glass_reason_label()}
          </label>
          <textarea
            id="break-glass-reason"
            bind:value={reason}
            rows="4"
            required
            maxlength="2000"
            class="block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          ></textarea>
          <p class="mt-1 text-xs text-warning">
            {m.admin_reason_pii_warning()}
          </p>
        </div>
        <div class="flex items-start gap-2">
          <input
            id="break-glass-confirm"
            type="checkbox"
            bind:checked={confirmed}
            class="mt-1"
          />
          <label
            for="break-glass-confirm"
            class="text-xs text-stone-700 dark:text-stone-300"
          >
            {m.admin_superusers_break_glass_confirm_label()}
          </label>
        </div>
        <button
          type="submit"
          disabled={isSubmitting || !confirmed}
          class="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting
            ? m.common_processing()
            : m.admin_superusers_break_glass_enter_button()}
        </button>
      </form>
    </div>
  {/if}
</div>

<!-- WebAuthn step-up gate (FR-111) -->
<WebAuthnGatePrompt
  bind:isOpen={gateOpen}
  action={pendingAction}
  onSuccess={handleGateSuccess}
  onCancel={handleGateCancel}
  onError={handleGateError}
/>
