<script lang="ts">
  /**
   * Admin — Superuser IP allowlist editor (Phase 15 / FR-072 + FR-111 T955).
   *
   * The list is canonicalised on the backend (overlapping CIDRs collapse,
   * private/public ranges are sorted) so the UI re-loads after a successful
   * PATCH to display the persisted set.
   *
   * Per-line entry keeps the editor approachable; the backend returns 422
   * with a row-level error when a CIDR is malformed.
   */

  import { page } from '$app/stores';
  import { ApiError } from '$lib/api/client';
  import {
    superuserApi,
    type SuperuserSummary,
  } from '$lib/api/superusers';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  const superuserId = $derived($page.params.id);

  let summary = $state<SuperuserSummary | null>(null);
  let isLoading = $state(true);
  let error = $state<string | null>(null);
  let banner = $state<string | null>(null);
  let editorValue = $state('');
  let isSaving = $state(false);
  let invalidCidrs = $state<string[]>([]);

  async function load() {
    isLoading = true;
    error = null;
    try {
      const result = await superuserApi.list();
      const found = result.items.find((row) => row.id === superuserId);
      if (!found) {
        error = m.admin_superusers_ip_allowlist_not_found();
        summary = null;
        return;
      }
      summary = found;
      editorValue = (found.allowed_ip_cidrs ?? []).join('\n');
    } catch (err) {
      error = mapError(err, m.admin_superusers_error_load());
    } finally {
      isLoading = false;
    }
  }

  $effect(() => {
    // Reference superuserId so the effect re-runs when the route param
    // changes; the value itself is not used directly here.
    void superuserId;
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
      // Backend 422 surfaces the offending CIDRs in `detail.invalid_cidrs`
      // when present.  We attempt to extract them defensively.
      return err.detail || err.message || fallback;
    }
    if (err instanceof Error) return err.message;
    return fallback;
  }

  function formatDate(s: string | null): string {
    if (!s) return '-';
    return new Date(s).toLocaleString(getLocale());
  }

  function parseLines(raw: string): string[] {
    return raw
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  }

  /**
   * Lightweight client-side CIDR shape check.  Definitive validation is
   * server-side; this pre-flight prevents the most common typos from
   * burning a 422 round-trip.
   */
  function looksLikeCidr(value: string): boolean {
    const v4 = /^\d{1,3}(?:\.\d{1,3}){3}\/\d{1,2}$/;
    const v6 = /^[0-9a-fA-F:]+\/\d{1,3}$/;
    return v4.test(value) || v6.test(value);
  }

  async function handleSave(e: Event) {
    e.preventDefault();
    if (!summary) return;
    isSaving = true;
    error = null;
    banner = null;
    invalidCidrs = [];

    const lines = parseLines(editorValue);
    const invalid = lines.filter((line) => !looksLikeCidr(line));
    if (invalid.length > 0) {
      invalidCidrs = invalid;
      error = m.admin_superusers_ip_allowlist_invalid_local();
      isSaving = false;
      return;
    }

    try {
      const result = await superuserApi.updateIpAllowlist(summary.id, lines);
      banner = m.admin_superusers_ip_allowlist_saved({
        time: formatDate(result.updated_at),
      });
      // Reload from canonicalised server state.
      await load();
    } catch (err) {
      error = mapError(err, m.admin_superusers_ip_allowlist_save_failed());
    } finally {
      isSaving = false;
    }
  }
</script>

<svelte:head>
  <title>{m.admin_superusers_ip_allowlist_heading()} - Admin - Echoroo</title>
</svelte:head>

<div class="px-2 py-2">
  <div class="mb-6 flex items-start justify-between">
    <div>
      <h1 class="text-3xl font-bold text-stone-900 dark:text-stone-100">
        {m.admin_superusers_ip_allowlist_heading()}
      </h1>
      <p class="mt-2 text-sm text-stone-600 dark:text-stone-400">
        {m.admin_superusers_ip_allowlist_description()}
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
      <div>{error}</div>
      {#if invalidCidrs.length > 0}
        <ul class="m-0 mt-2 list-disc pl-6 text-xs">
          {#each invalidCidrs as cidr}
            <li class="font-mono">{cidr}</li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}

  {#if isLoading}
    <div class="py-12 text-center text-sm text-stone-500">{m.common_loading()}</div>
  {:else if summary}
    <div class="rounded-md border border-card bg-surface-card p-4">
      <dl class="mb-4 grid grid-cols-1 gap-3 text-xs sm:grid-cols-2">
        <div>
          <dt class="text-stone-500">
            {m.admin_superusers_ip_allowlist_field_user_id()}
          </dt>
          <dd class="font-mono">{summary.user_id}</dd>
        </div>
        <div>
          <dt class="text-stone-500">
            {m.admin_superusers_ip_allowlist_field_added_at()}
          </dt>
          <dd>{formatDate(summary.added_at)}</dd>
        </div>
      </dl>
      <form onsubmit={handleSave} class="space-y-4">
        <div>
          <label
            for="ip-cidrs"
            class="mb-1 block text-xs font-medium text-stone-700 dark:text-stone-300"
          >
            {m.admin_superusers_ip_allowlist_label()}
          </label>
          <textarea
            id="ip-cidrs"
            bind:value={editorValue}
            rows="8"
            placeholder="10.0.0.0/8&#10;192.168.1.0/24&#10;2001:db8::/32"
            class="block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 font-mono text-xs focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          ></textarea>
          <p class="mt-1 text-xs text-stone-500">
            {m.admin_superusers_ip_allowlist_hint()}
          </p>
        </div>
        <button
          type="submit"
          disabled={isSaving || summary.revoked_at !== null}
          class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSaving ? m.common_processing() : m.admin_superusers_ip_allowlist_save()}
        </button>
        {#if summary.revoked_at !== null}
          <p class="text-xs text-stone-500">
            {m.admin_superusers_ip_allowlist_revoked_disabled()}
          </p>
        {/if}
      </form>
    </div>
  {/if}
</div>
