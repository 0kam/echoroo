<script lang="ts">
  /**
   * Trusted-user list with status filter and per-row actions (T520).
   *
   * Presentational shell: the parent owns the list query + row mutations
   * and passes the resolved items / loading flags down. The status filter
   * is bound back up so the parent's query key reacts to it. Row actions
   * are delegated via callbacks.
   */
  import * as m from '$lib/paraglide/messages';
  import { getLocale } from '$lib/paraglide/runtime';
  import {
    getProjectTrustedStatusLabel,
    getProjectTrustedStatusClass,
  } from '$lib/utils/statusFormatters';
  import type { ProjectTrustedStatus, TrustedUser } from '$lib/types';
  import { permissionLabel, type TrustedFlash } from './trustedPermissions';

  /**
   * Status filter: `'all'` is a UI-only sentinel that the parent maps to
   * `undefined` before hitting the API.
   */
  type StatusFilter = 'all' | ProjectTrustedStatus;

  interface Props {
    statusFilter: StatusFilter;
    rowFlash: TrustedFlash;
    isLoading: boolean;
    isError: boolean;
    items: TrustedUser[];
    isAdmin: boolean;
    isOwner: boolean;
    onExtend: (row: TrustedUser) => void;
    onEditPerms: (row: TrustedUser) => void;
    onRevoke: (row: TrustedUser) => void;
  }

  let {
    statusFilter = $bindable(),
    rowFlash,
    isLoading,
    isError,
    items,
    isAdmin,
    isOwner,
    onExtend,
    onEditPerms,
    onRevoke,
  }: Props = $props();

  function formatDateTime(iso: string): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString(getLocale());
    } catch {
      return iso;
    }
  }

  function statusLabel(s: ProjectTrustedStatus): string {
    return getProjectTrustedStatusLabel(s, {
      active: m.trusted_users_list_status_active,
      expired: m.trusted_users_list_status_expired,
      revoked: m.trusted_users_list_status_revoked,
    });
  }

  function statusBadgeClass(s: ProjectTrustedStatus): string {
    return getProjectTrustedStatusClass(s);
  }
</script>

<section
  class="rounded-lg bg-surface-card p-6 shadow"
  aria-labelledby="trusted-list-title"
  data-testid="trusted-users-list"
>
  <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
    <h2 id="trusted-list-title" class="text-lg font-semibold text-stone-900">
      {m.trusted_users_list_title()}
    </h2>

    <label class="flex items-center gap-2 text-sm text-stone-700">
      <span>{m.trusted_users_list_filter_label()}</span>
      <select
        data-testid="trusted-list-filter"
        bind:value={statusFilter}
        class="rounded-md border border-stone-300 bg-surface-card px-2 py-1 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500"
      >
        <option value="active">{m.trusted_users_list_filter_active()}</option>
        <option value="expired">{m.trusted_users_list_filter_expired()}</option>
        <option value="revoked">{m.trusted_users_list_filter_revoked()}</option>
        <option value="all">{m.trusted_users_list_filter_all()}</option>
      </select>
    </label>
  </div>

  {#if rowFlash.kind === 'success'}
    <p
      data-testid="trusted-row-flash-success"
      role="status"
      class="mb-4 rounded-md bg-success-light px-4 py-3 text-sm text-success"
    >
      {rowFlash.message}
    </p>
  {:else if rowFlash.kind === 'error'}
    <p
      data-testid="trusted-row-flash-error"
      role="alert"
      class="mb-4 rounded-md bg-danger-light px-4 py-3 text-sm text-danger"
    >
      {rowFlash.message}
    </p>
  {/if}

  {#if isLoading}
    <p class="text-sm text-stone-500">{m.trusted_users_list_loading()}</p>
  {:else if isError}
    <p class="text-sm text-danger" role="alert">
      {m.trusted_error_load()}
    </p>
  {:else if items.length === 0}
    <p
      data-testid="trusted-list-empty"
      class="text-sm italic text-stone-500"
    >
      {m.trusted_users_list_empty()}
    </p>
  {:else}
    <div class="overflow-x-auto">
      <table class="min-w-full divide-y divide-stone-200 text-sm">
        <thead>
          <tr class="text-left text-xs font-medium uppercase tracking-wider text-stone-500">
            <th scope="col" class="py-2 pr-3">
              {m.trusted_users_list_column_user()}
            </th>
            <th scope="col" class="py-2 pr-3">
              {m.trusted_users_list_column_permissions()}
            </th>
            <th scope="col" class="py-2 pr-3">
              {m.trusted_users_list_column_expires_at()}
            </th>
            <th scope="col" class="py-2 pr-3">
              {m.trusted_users_list_column_status()}
            </th>
            {#if isAdmin}
              <th scope="col" class="py-2 text-right">
                {m.trusted_users_list_column_actions()}
              </th>
            {/if}
          </tr>
        </thead>
        <tbody class="divide-y divide-stone-100">
          {#each items as row (row.id)}
            <tr data-testid={`trusted-row-${row.id}`}>
              <td class="py-3 pr-3 align-top">
                <code class="text-xs text-stone-700">{row.user_id}</code>
              </td>
              <td class="py-3 pr-3 align-top">
                <ul class="space-y-0.5 text-xs text-stone-700">
                  {#each row.granted_permissions as perm (perm)}
                    <li>{permissionLabel(perm)}</li>
                  {/each}
                </ul>
              </td>
              <td class="py-3 pr-3 align-top text-xs text-stone-700">
                {formatDateTime(row.expires_at)}
              </td>
              <td class="py-3 pr-3 align-top">
                <span
                  class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {statusBadgeClass(
                    row.status,
                  )}"
                >
                  {statusLabel(row.status)}
                </span>
              </td>
              {#if isAdmin}
                <!--
                  Round 2 polish (Minor 1): Admins still see the action
                  buttons but the controls render disabled with an
                  Owner-only tooltip rather than disappearing entirely.
                  This makes the missing capability discoverable instead
                  of silent.
                -->
                <td class="py-3 text-right align-top">
                  <div class="flex flex-wrap justify-end gap-2">
                    {#if row.status === 'active'}
                      <button
                        type="button"
                        data-testid={`trusted-extend-${row.id}`}
                        onclick={() => onExtend(row)}
                        disabled={!isOwner}
                        title={isOwner ? undefined : m.trusted_user_owner_only_tooltip()}
                        aria-disabled={!isOwner}
                        class="rounded-md border border-stone-300 bg-surface-card px-3 py-1 text-xs font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-surface-card"
                      >
                        {m.trusted_user_extend_button()}
                      </button>
                      <button
                        type="button"
                        data-testid={`trusted-edit-perms-${row.id}`}
                        onclick={() => onEditPerms(row)}
                        disabled={!isOwner}
                        title={isOwner ? undefined : m.trusted_user_owner_only_tooltip()}
                        aria-disabled={!isOwner}
                        class="rounded-md border border-stone-300 bg-surface-card px-3 py-1 text-xs font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-surface-card"
                      >
                        {m.trusted_user_edit_permissions_button()}
                      </button>
                      <button
                        type="button"
                        data-testid={`trusted-revoke-${row.id}`}
                        onclick={() => onRevoke(row)}
                        disabled={!isOwner}
                        title={isOwner ? undefined : m.trusted_user_owner_only_tooltip()}
                        aria-disabled={!isOwner}
                        class="rounded-md border border-danger/30 bg-surface-card px-3 py-1 text-xs font-medium text-danger hover:bg-danger-light disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-surface-card"
                      >
                        {m.trusted_user_revoke_button()}
                      </button>
                    {/if}
                  </div>
                </td>
              {/if}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>
