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
  import WebAuthnGatePrompt from '$lib/components/admin/WebAuthnGatePrompt.svelte';

  const superuserId = $derived($page.params.id);

  let summary = $state<SuperuserSummary | null>(null);
  let isLoading = $state(true);
  let error = $state<string | null>(null);
  let banner = $state<string | null>(null);
  let editorValue = $state('');
  let isSaving = $state(false);

  /**
   * Per-line CIDR validation failures returned by the backend
   * (Phase 15 Batch 5b R3 Codex Minor 2 fix).
   *
   * ``lineNumber`` is **1-indexed** — Pydantic's ``loc`` tuple is
   * 0-indexed but operators expect "row N" to match the textarea
   * gutter, so we add 1 before storing here.  ``value`` carries the
   * raw line text the operator submitted, ``message`` carries the
   * human-readable validator error (`msg` field of the Pydantic
   * detail entry).
   */
  interface InvalidCidrEntry {
    lineNumber: number;
    value: string;
    message: string;
  }
  let invalidCidrs = $state<InvalidCidrEntry[]>([]);

  // WebAuthn step-up gate (FR-111).
  let gateOpen = $state(false);
  let pendingAction = $state<(() => Promise<void>) | null>(null);

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
      return err.detail || err.message || fallback;
    }
    if (err instanceof Error) return err.message;
    return fallback;
  }

  /**
   * Pull per-line CIDR errors out of a FastAPI 422 ``detail`` array.
   *
   * Pydantic emits one entry per offending field path; for our
   * ``allowed_ip_cidrs: list[str]`` validator each entry's ``loc`` ends
   * with the integer index of the bad row.  We pair the (1-indexed)
   * line number with the raw line value and the validator's
   * ``msg`` so the UI can render
   * ``行 {lineNumber}: {value} — {message}``.
   *
   * Phase 15 Batch 5b R3 (Codex Minor 2 fix): the previous return
   * shape exposed only the line value, so the UI could not render a
   * row number even though ``loc`` already carried it.  We now bundle
   * ``lineNumber`` (Pydantic 0-indexed → operator 1-indexed) with the
   * value and message.  Entries that cannot be paired with a line
   * (no numeric ``loc`` part) fall through to ``aggregateMessages``
   * so the user still sees the explanation in the alert banner.
   */
  function extractInvalidLines(
    err: ApiError,
    submittedLines: string[],
  ): { entries: InvalidCidrEntry[]; aggregateMessages: string[] } {
    const entries: InvalidCidrEntry[] = [];
    const aggregateMessages: string[] = [];
    const body = err.body;
    if (!body || typeof body !== 'object') {
      return { entries, aggregateMessages };
    }
    const detail = (body as { detail?: unknown }).detail;
    if (!Array.isArray(detail)) return { entries, aggregateMessages };
    for (const entry of detail) {
      if (!entry || typeof entry !== 'object') continue;
      const loc = (entry as { loc?: unknown }).loc;
      const msg = (entry as { msg?: unknown }).msg;
      const messageText = typeof msg === 'string' ? msg : '';
      let matchedLine: { lineNumber: number; value: string } | null = null;
      if (Array.isArray(loc)) {
        // Find the trailing numeric index in the loc tuple.
        for (let i = loc.length - 1; i >= 0; i -= 1) {
          const part = loc[i];
          if (
            typeof part === 'number' &&
            part >= 0 &&
            part < submittedLines.length
          ) {
            matchedLine = {
              lineNumber: part + 1,
              value: submittedLines[part]!,
            };
            break;
          }
        }
      }
      if (matchedLine) {
        entries.push({
          lineNumber: matchedLine.lineNumber,
          value: matchedLine.value,
          message: messageText,
        });
      } else if (messageText) {
        // No row index in `loc` — surface the message in the banner
        // so the operator still understands what failed.
        aggregateMessages.push(messageText);
      }
    }
    return { entries, aggregateMessages };
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
   * Phase 15 Batch 5b R2 (Codex Minor 1 fix).  Client-side CIDR regex
   * validation has been removed — the backend
   * (``ipaddress.ip_network(strict=False)`` inside the Pydantic
   * validator) is the single source of truth.  The previous regex
   * disagreed with the backend in both directions (e.g. it rejected
   * bare-IP entries the backend canonicalised to ``/32`` and accepted
   * ``999.999.999.999/99``-style garbage the backend immediately
   * threw out), so we now POST whatever the operator typed and let
   * the 422 response describe the offending rows.
   */
  function handleSave(e: Event) {
    e.preventDefault();
    if (!summary) return;
    error = null;
    banner = null;
    invalidCidrs = [];

    const lines = parseLines(editorValue);
    const targetSummary = summary;
    pendingAction = async () => {
      isSaving = true;
      try {
        const result = await superuserApi.updateIpAllowlist(targetSummary.id, lines);
        banner = m.admin_superusers_ip_allowlist_saved({
          time: formatDate(result.updated_at),
        });
        // Reload from canonicalised server state.
        await load();
      } catch (err) {
        if (err instanceof ApiError && err.status === 422) {
          const { entries, aggregateMessages } = extractInvalidLines(
            err,
            lines,
          );
          invalidCidrs = entries;
          // Build the banner message: prefer aggregate messages (entries
          // that could not be paired with a row), then fall back to a
          // distinct list of per-line messages so the alert still names
          // the failure mode without duplicating the rendered list below.
          const bannerMessages = aggregateMessages.slice();
          if (bannerMessages.length === 0 && entries.length > 0) {
            const distinctEntryMessages = Array.from(
              new Set(entries.map((e) => e.message).filter((m) => m.length > 0)),
            );
            bannerMessages.push(...distinctEntryMessages);
          }
          error =
            bannerMessages.length > 0
              ? bannerMessages.join('; ')
              : m.admin_superusers_ip_allowlist_save_failed();
        } else {
          error = mapError(err, m.admin_superusers_ip_allowlist_save_failed());
        }
      } finally {
        isSaving = false;
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
        <div class="mt-2 text-xs">
          <span class="font-medium">{m.admin_superusers_ip_allowlist_invalid_lines_label()}</span>
          <ul class="m-0 mt-1 list-disc pl-6">
            {#each invalidCidrs as entry (entry.lineNumber)}
              <li class="font-mono">
                {m.admin_superusers_ip_allowlist_invalid_line_format({
                  lineNumber: entry.lineNumber,
                  value: entry.value,
                  message: entry.message,
                })}
              </li>
            {/each}
          </ul>
        </div>
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

<!-- WebAuthn step-up gate (FR-111) -->
<WebAuthnGatePrompt
  bind:isOpen={gateOpen}
  action={pendingAction}
  onSuccess={handleGateSuccess}
  onCancel={handleGateCancel}
  onError={handleGateError}
/>
