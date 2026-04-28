<script lang="ts">
  /**
   * Trusted User management page (Phase 10 / T520, FR-050).
   *
   * Surfaces the four Trusted overlay endpoints from
   * `specs/006-permissions-redesign/contracts/trusted.yaml`:
   *
   * - `GET    /web-api/v1/projects/{id}/trusted-users`            (Owner / Admin)
   * - `POST   /web-api/v1/projects/{id}/trusted-users`            (Owner only)
   * - `PATCH  /web-api/v1/projects/{id}/trusted-users/{tuId}`     (Owner only)
   * - `DELETE /web-api/v1/projects/{id}/trusted-users/{tuId}`     (Owner only)
   *
   * Permission UI gate
   * ------------------
   * - Owner: full read + write surface (invite form, extend / edit /
   *   revoke buttons).
   * - Admin: read-only — list visible, invite form + per-row actions
   *   hidden behind `trusted_user_admin_readonly_notice`.
   * - Member / Viewer / non-member / Guest: redirected back to the
   *   project detail page (the backend would 403 anyway, but routing
   *   them away keeps the shell clean and avoids inviting an "I'm
   *   missing toggles" support ticket).
   *
   * The role lookup leans on `project.current_user_role` (Phase 9
   * polish round 2 Major 2) so we never probe the admin-only
   * `/members` endpoint as part of role detection.
   *
   * TanStack Query is used for the list query and for the four mutations
   * (invite / extend / edit-permissions / revoke). On every successful
   * mutation we invalidate the list query so the UI reflects the new
   * server state without a manual reload.
   *
   * Theme: Rosé Pine (Light=Dawn, Dark=Main). Colour tokens come from
   * the existing `tailwind.config` palette (`primary`, `surface-card`,
   * `danger`, `success`, `warning`).
   */

  import { goto } from '$app/navigation';
  import {
    createMutation,
    createQuery,
    useQueryClient,
  } from '@tanstack/svelte-query';
  import { ApiError } from '$lib/api/client';
  import { projectsApi } from '$lib/api/projects';
  import * as m from '$lib/paraglide/messages';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import type {
    Project,
    ProjectTrustedStatus,
    TrustedGrantedPermission,
    TrustedUser,
    TrustedUserInviteRequest,
    TrustedUserListResponse,
    TrustedUserUpdateRequest,
  } from '$lib/types';

  /** Page server-load output. */
  let { data } = $props();
  const projectId = $derived(data.projectId);

  // ---------------------------------------------------------------------------
  // Project + role gate
  // ---------------------------------------------------------------------------

  let project = $state<Project | null>(null);
  let projectLoading = $state(true);
  let projectError = $state<string | null>(null);

  /**
   * Trusted overlay management is Owner-only for mutations, with Admins
   * receiving a read-only view. Members / Viewers / non-members are
   * redirected back to the project detail page so they don't end up on
   * a page they cannot interact with.
   */
  const isOwner = $derived(project?.current_user_role === 'owner');
  const isAdmin = $derived(
    project?.current_user_role === 'owner' ||
      project?.current_user_role === 'admin',
  );

  $effect(() => {
    void (async () => {
      projectLoading = true;
      projectError = null;
      try {
        const p = await projectsApi.get(projectId);
        project = p;
        const role = p.current_user_role;
        if (role !== 'owner' && role !== 'admin') {
          // Non-admins do not get the overlay management page. Redirect
          // back to the project detail surface — the backend would 403
          // the list call anyway.
          await goto(localizeHref(`/projects/${projectId}`));
          return;
        }
      } catch (err) {
        if (err instanceof ApiError) {
          projectError = err.detail || err.message;
        } else {
          projectError = m.trusted_error_load();
        }
      } finally {
        projectLoading = false;
      }
    })();
  });

  // ---------------------------------------------------------------------------
  // Trusted Users list query
  // ---------------------------------------------------------------------------

  /**
   * Status filter: `'all'` is a UI-only sentinel. `undefined` is sent to
   * the API for the "all" case, otherwise the literal `ProjectTrustedStatus`.
   */
  type StatusFilter = 'all' | ProjectTrustedStatus;
  let statusFilter = $state<StatusFilter>('active');

  const queryClient = useQueryClient();

  const trustedListQuery = $derived(
    createQuery<TrustedUserListResponse>({
      queryKey: ['trusted-users', projectId, statusFilter],
      queryFn: () =>
        projectsApi.listTrustedUsers(
          projectId,
          statusFilter === 'all' ? undefined : statusFilter,
        ),
      // Avoid refetching every page focus while the user is fiddling with
      // the form — they will hit "Send" or "Refresh" explicitly.
      refetchOnWindowFocus: false,
      enabled: !!projectId && isAdmin,
      retry: false,
    }),
  );

  const trustedItems = $derived($trustedListQuery.data?.items ?? []);

  function invalidateTrustedList() {
    queryClient.invalidateQueries({ queryKey: ['trusted-users', projectId] });
  }

  // ---------------------------------------------------------------------------
  // Invite form state
  // ---------------------------------------------------------------------------

  /**
   * Allowlisted permissions (mirrors `TRUSTED_ALLOWED_PERMISSIONS` /
   * FR-012). Order is stable so the form layout doesn't shuffle between
   * renders.
   */
  const ALL_TRUSTED_PERMISSIONS: ReadonlyArray<TrustedGrantedPermission> = [
    'view_media',
    'view_detection',
    'view_precise_location',
    'download',
    'export',
    'search_within_project',
    'vote',
    'comment',
  ];

  function permissionLabel(p: TrustedGrantedPermission): string {
    switch (p) {
      case 'view_media':
        return m.trusted_permission_view_media();
      case 'view_detection':
        return m.trusted_permission_view_detection();
      case 'view_precise_location':
        return m.trusted_permission_view_precise_location();
      case 'download':
        return m.trusted_permission_download();
      case 'export':
        return m.trusted_permission_export();
      case 'search_within_project':
        return m.trusted_permission_search_within_project();
      case 'vote':
        return m.trusted_permission_vote();
      case 'comment':
        return m.trusted_permission_comment();
    }
  }

  let inviteEmail = $state('');
  let invitePermissions = $state<Record<TrustedGrantedPermission, boolean>>({
    view_media: true,
    view_detection: true,
    view_precise_location: false,
    download: false,
    export: false,
    search_within_project: false,
    vote: false,
    comment: false,
  });
  /** Default 90 days, hard-capped at 365 (FR-043). */
  let inviteDurationSeconds = $state<number>(90 * 24 * 3600);
  let inviteFlash = $state<
    | { kind: 'idle' }
    | { kind: 'success'; message: string }
    | { kind: 'error'; message: string }
  >({ kind: 'idle' });

  const inviteSelectedPermissions = $derived(
    ALL_TRUSTED_PERMISSIONS.filter((p) => invitePermissions[p]),
  );
  const inviteFormValid = $derived(
    inviteEmail.trim().length > 0 && inviteSelectedPermissions.length > 0,
  );

  const inviteMutation = createMutation<
    { invitation_id: string },
    Error,
    TrustedUserInviteRequest
  >({
    mutationFn: (body) => projectsApi.inviteTrustedUser(projectId, body),
    onSuccess: () => {
      inviteFlash = {
        kind: 'success',
        message: m.trusted_invite_success(),
      };
      // Reset the email but keep the permission selection so the Owner
      // can send a follow-up invitation with the same permissions
      // without re-clicking every checkbox.
      inviteEmail = '';
      invalidateTrustedList();
    },
    onError: (err) => {
      inviteFlash = { kind: 'error', message: mapInviteError(err) };
    },
  });

  function mapInviteError(err: Error): string {
    if (err instanceof ApiError) {
      switch (err.code) {
        case 'ERR_SELF_TRUSTED_INVALID':
          return m.trusted_error_self_invalid();
        case 'ERR_TRUSTED_TARGET_INVALID':
          return m.trusted_error_target_invalid();
        case 'ERR_INVALID_TRUSTED_PERMISSION':
          return m.trusted_error_permission_invalid();
        case 'ERR_INVITATION_PENDING':
          return m.trusted_error_invitation_pending();
      }
    }
    return m.trusted_error_invite_generic();
  }

  function submitInvite() {
    if (!inviteFormValid || $inviteMutation.isPending) return;
    inviteFlash = { kind: 'idle' };
    $inviteMutation.mutate({
      email: inviteEmail.trim(),
      granted_permissions: inviteSelectedPermissions,
      duration_seconds: inviteDurationSeconds,
    });
  }

  // ---------------------------------------------------------------------------
  // Per-row mutations: revoke / extend / edit-permissions
  // ---------------------------------------------------------------------------

  let rowFlash = $state<
    | { kind: 'idle' }
    | { kind: 'success'; message: string }
    | { kind: 'error'; message: string }
  >({ kind: 'idle' });

  // --- Revoke modal --------------------------------------------------------
  let revokeTarget = $state<TrustedUser | null>(null);

  const revokeMutation = createMutation<void, Error, string>({
    mutationFn: (trustedUserId) =>
      projectsApi.revokeTrustedUser(projectId, trustedUserId),
    onSuccess: () => {
      rowFlash = {
        kind: 'success',
        message: m.trusted_user_revoke_success(),
      };
      revokeTarget = null;
      invalidateTrustedList();
    },
    onError: () => {
      rowFlash = { kind: 'error', message: m.trusted_error_revoke_generic() };
    },
  });

  // --- Extend modal --------------------------------------------------------
  let extendTarget = $state<TrustedUser | null>(null);
  let extendNewExpiry = $state<string>('');

  const extendMutation = createMutation<
    TrustedUser,
    Error,
    { trustedUserId: string; body: TrustedUserUpdateRequest }
  >({
    mutationFn: ({ trustedUserId, body }) =>
      projectsApi.updateTrustedUser(projectId, trustedUserId, body),
    onSuccess: () => {
      rowFlash = {
        kind: 'success',
        message: m.trusted_user_extend_success(),
      };
      extendTarget = null;
      extendNewExpiry = '';
      invalidateTrustedList();
    },
    onError: (err) => {
      rowFlash = { kind: 'error', message: mapUpdateError(err) };
    },
  });

  // --- Edit-permissions modal ---------------------------------------------
  let editPermsTarget = $state<TrustedUser | null>(null);
  let editPermsSelection = $state<Record<TrustedGrantedPermission, boolean>>({
    view_media: false,
    view_detection: false,
    view_precise_location: false,
    download: false,
    export: false,
    search_within_project: false,
    vote: false,
    comment: false,
  });

  const editPermsMutation = createMutation<
    TrustedUser,
    Error,
    { trustedUserId: string; body: TrustedUserUpdateRequest }
  >({
    mutationFn: ({ trustedUserId, body }) =>
      projectsApi.updateTrustedUser(projectId, trustedUserId, body),
    onSuccess: () => {
      rowFlash = {
        kind: 'success',
        message: m.trusted_user_edit_permissions_success(),
      };
      editPermsTarget = null;
      invalidateTrustedList();
    },
    onError: (err) => {
      rowFlash = { kind: 'error', message: mapUpdateError(err) };
    },
  });

  function mapUpdateError(err: Error): string {
    if (err instanceof ApiError) {
      switch (err.code) {
        case 'ERR_INVALID_TRUSTED_PERMISSION':
          return m.trusted_error_permission_invalid();
        case 'ERR_NO_OP':
          return m.trusted_error_no_op();
        case 'ERR_AMBIGUOUS_EXPIRY':
          return m.trusted_error_ambiguous_expiry();
        case 'ERR_TRUSTED_UPDATE_INVALID':
          return m.trusted_error_update_invalid();
      }
    }
    return m.trusted_error_extend_generic();
  }

  function openExtendModal(row: TrustedUser): void {
    extendTarget = row;
    // Seed the picker with the current expiry so the modal feels
    // pre-populated rather than blank.
    extendNewExpiry = isoToInputValue(row.expires_at);
    rowFlash = { kind: 'idle' };
  }

  function submitExtend(): void {
    if (!extendTarget || $extendMutation.isPending) return;
    if (!extendNewExpiry) return;
    // The native datetime-local control returns a value like
    // `2026-12-31T23:59` (no timezone). The backend expects ISO-8601;
    // we treat the value as UTC-equivalent and append `Z`.
    const isoCandidate = new Date(extendNewExpiry).toISOString();
    $extendMutation.mutate({
      trustedUserId: extendTarget.id,
      body: { expires_at: isoCandidate },
    });
  }

  function openEditPermsModal(row: TrustedUser): void {
    editPermsTarget = row;
    const granted = new Set(row.granted_permissions);
    editPermsSelection = {
      view_media: granted.has('view_media'),
      view_detection: granted.has('view_detection'),
      view_precise_location: granted.has('view_precise_location'),
      download: granted.has('download'),
      export: granted.has('export'),
      search_within_project: granted.has('search_within_project'),
      vote: granted.has('vote'),
      comment: granted.has('comment'),
    };
    rowFlash = { kind: 'idle' };
  }

  const editPermsSelectedList = $derived(
    ALL_TRUSTED_PERMISSIONS.filter((p) => editPermsSelection[p]),
  );

  function submitEditPerms(): void {
    if (!editPermsTarget || $editPermsMutation.isPending) return;
    if (editPermsSelectedList.length === 0) return;
    $editPermsMutation.mutate({
      trustedUserId: editPermsTarget.id,
      body: { granted_permissions: editPermsSelectedList },
    });
  }

  function openRevokeModal(row: TrustedUser): void {
    revokeTarget = row;
    rowFlash = { kind: 'idle' };
  }

  function confirmRevoke(): void {
    if (!revokeTarget || $revokeMutation.isPending) return;
    $revokeMutation.mutate(revokeTarget.id);
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /**
   * Convert an ISO timestamp to the value format accepted by an
   * `<input type="datetime-local">` control: `YYYY-MM-DDTHH:MM`.
   * Returns the trailing minutes only (no seconds / timezone).
   */
  function isoToInputValue(iso: string): string {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const pad = (n: number) => String(n).padStart(2, '0');
    return (
      `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
      `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
    );
  }

  function formatDateTime(iso: string): string {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString(getLocale());
    } catch {
      return iso;
    }
  }

  function statusLabel(s: ProjectTrustedStatus): string {
    switch (s) {
      case 'active':
        return m.trusted_users_list_status_active();
      case 'expired':
        return m.trusted_users_list_status_expired();
      case 'revoked':
        return m.trusted_users_list_status_revoked();
    }
  }

  function statusBadgeClass(s: ProjectTrustedStatus): string {
    switch (s) {
      case 'active':
        return 'bg-success-light text-success';
      case 'expired':
        return 'bg-warning-light text-warning';
      case 'revoked':
        return 'bg-stone-100 text-stone-700';
    }
  }
</script>

<svelte:head>
  <title>{m.trusted_page_title()} - Echoroo</title>
</svelte:head>

<div
  class="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8"
  data-testid="trusted-page"
>
  <header class="mb-6">
    <h1 class="text-3xl font-bold text-stone-900">{m.trusted_page_title()}</h1>
    <p class="mt-1 text-sm text-stone-600">{m.trusted_page_subtitle()}</p>
    {#if project}
      <p class="mt-1 text-xs text-stone-500">{project.name}</p>
    {/if}
  </header>

  {#if projectLoading}
    <div class="flex items-center justify-center py-12">
      <svg
        class="h-8 w-8 animate-spin text-primary-600"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        aria-hidden="true"
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
    </div>
  {:else if projectError}
    <div class="rounded-md bg-danger-light p-4" role="alert">
      <p class="text-sm font-medium text-danger">{projectError}</p>
    </div>
  {:else if project}
    {#if !isOwner && isAdmin}
      <div
        data-testid="trusted-admin-readonly-notice"
        class="mb-6 rounded-md bg-info-light px-4 py-3 text-sm text-info"
        role="status"
      >
        {m.trusted_user_admin_readonly_notice()}
      </div>
    {/if}

    <!-- Invite form: Owner-only ------------------------------------- -->
    {#if isOwner}
      <section
        class="mb-8 rounded-lg bg-surface-card p-6 shadow"
        aria-labelledby="trusted-invite-form-title"
        data-testid="trusted-invite-form"
      >
        <h2
          id="trusted-invite-form-title"
          class="mb-4 text-lg font-semibold text-stone-900"
        >
          {m.trusted_invite_form_title()}
        </h2>

        <div class="space-y-5">
          <div>
            <label
              for="trusted-invite-email"
              class="block text-sm font-medium text-stone-700"
            >
              {m.trusted_invite_email_label()}
            </label>
            <input
              id="trusted-invite-email"
              data-testid="trusted-invite-email-input"
              type="email"
              bind:value={inviteEmail}
              placeholder={m.trusted_invite_email_placeholder()}
              autocomplete="email"
              class="mt-1 block w-full max-w-md rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:cursor-not-allowed disabled:bg-stone-100 disabled:opacity-60"
              disabled={$inviteMutation.isPending}
            />
          </div>

          <fieldset>
            <legend class="block text-sm font-medium text-stone-700">
              {m.trusted_invite_granted_permissions_label()}
            </legend>
            <p class="mt-0.5 text-xs text-stone-500">
              {m.trusted_invite_granted_permissions_help()}
            </p>
            <div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {#each ALL_TRUSTED_PERMISSIONS as perm (perm)}
                <label class="flex items-start gap-2 text-sm text-stone-700">
                  <input
                    data-testid={`trusted-invite-perm-${perm}`}
                    type="checkbox"
                    bind:checked={invitePermissions[perm]}
                    disabled={$inviteMutation.isPending}
                    class="mt-0.5 h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500 disabled:cursor-not-allowed disabled:opacity-60"
                  />
                  <span>{permissionLabel(perm)}</span>
                </label>
              {/each}
            </div>
          </fieldset>

          <div>
            <label
              for="trusted-invite-duration"
              class="block text-sm font-medium text-stone-700"
            >
              {m.trusted_invite_duration_label()}
            </label>
            <p
              id="trusted-invite-duration-help"
              class="mt-0.5 text-xs text-stone-500"
            >
              {m.trusted_invite_duration_help()}
            </p>
            <select
              id="trusted-invite-duration"
              data-testid="trusted-invite-duration-select"
              bind:value={inviteDurationSeconds}
              disabled={$inviteMutation.isPending}
              aria-describedby="trusted-invite-duration-help"
              class="mt-1 block w-full max-w-xs rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:cursor-not-allowed disabled:bg-stone-100 disabled:opacity-60"
            >
              <option value={30 * 24 * 3600}>
                {m.trusted_invite_duration_30_days()}
              </option>
              <option value={90 * 24 * 3600}>
                {m.trusted_invite_duration_90_days()}
              </option>
              <option value={180 * 24 * 3600}>
                {m.trusted_invite_duration_180_days()}
              </option>
              <option value={365 * 24 * 3600}>
                {m.trusted_invite_duration_365_days()}
              </option>
            </select>
          </div>

          {#if inviteFlash.kind === 'success'}
            <p
              data-testid="trusted-invite-success"
              role="status"
              class="rounded-md bg-success-light px-4 py-3 text-sm text-success"
            >
              {inviteFlash.message}
            </p>
          {:else if inviteFlash.kind === 'error'}
            <p
              data-testid="trusted-invite-error"
              role="alert"
              class="rounded-md bg-danger-light px-4 py-3 text-sm text-danger"
            >
              {inviteFlash.message}
            </p>
          {/if}

          <div class="flex justify-end">
            <button
              type="button"
              data-testid="trusted-invite-submit"
              onclick={submitInvite}
              disabled={!inviteFormValid || $inviteMutation.isPending}
              class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {#if $inviteMutation.isPending}
                {m.trusted_invite_submitting_button()}
              {:else}
                {m.trusted_invite_submit_button()}
              {/if}
            </button>
          </div>
        </div>
      </section>
    {/if}

    <!-- Trusted Users list ------------------------------------------- -->
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

      {#if $trustedListQuery.isLoading}
        <p class="text-sm text-stone-500">{m.trusted_users_list_loading()}</p>
      {:else if $trustedListQuery.isError}
        <p class="text-sm text-danger" role="alert">
          {m.trusted_error_load()}
        </p>
      {:else if trustedItems.length === 0}
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
              {#each trustedItems as row (row.id)}
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
                            onclick={() => openExtendModal(row)}
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
                            onclick={() => openEditPermsModal(row)}
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
                            onclick={() => openRevokeModal(row)}
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
  {/if}
</div>

<!-- Revoke confirmation modal -->
{#if revokeTarget}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="trusted-revoke-modal-title"
    data-testid="trusted-revoke-modal"
  >
    <div class="w-full max-w-md overflow-y-auto rounded-lg bg-surface-card shadow-xl">
      <div class="border-b border-stone-200 px-6 py-4">
        <h2
          id="trusted-revoke-modal-title"
          class="m-0 text-lg font-semibold text-stone-900"
        >
          {m.trusted_user_revoke_confirm_title()}
        </h2>
      </div>
      <div class="p-6">
        <p class="m-0 text-sm leading-relaxed text-stone-700">
          {m.trusted_user_revoke_confirm_message()}
        </p>
      </div>
      <div class="flex justify-end gap-3 border-t border-stone-200 px-6 py-4">
        <button
          type="button"
          onclick={() => (revokeTarget = null)}
          disabled={$revokeMutation.isPending}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.common_cancel()}
        </button>
        <button
          type="button"
          data-testid="trusted-revoke-confirm"
          onclick={confirmRevoke}
          disabled={$revokeMutation.isPending}
          class="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.trusted_user_revoke_confirm_button()}
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- Extend modal -->
{#if extendTarget}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="trusted-extend-modal-title"
    data-testid="trusted-extend-modal"
  >
    <div class="w-full max-w-md overflow-y-auto rounded-lg bg-surface-card shadow-xl">
      <div class="border-b border-stone-200 px-6 py-4">
        <h2
          id="trusted-extend-modal-title"
          class="m-0 text-lg font-semibold text-stone-900"
        >
          {m.trusted_user_extend_modal_title()}
        </h2>
      </div>
      <div class="space-y-4 p-6">
        <p class="m-0 text-sm leading-relaxed text-stone-700">
          {m.trusted_user_extend_modal_help()}
        </p>
        <div>
          <label
            for="trusted-extend-expiry"
            class="block text-sm font-medium text-stone-700"
          >
            {m.trusted_user_extend_new_expiry_label()}
          </label>
          <input
            id="trusted-extend-expiry"
            data-testid="trusted-extend-expiry-input"
            type="datetime-local"
            bind:value={extendNewExpiry}
            class="mt-1 block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500"
          />
        </div>
      </div>
      <div class="flex justify-end gap-3 border-t border-stone-200 px-6 py-4">
        <button
          type="button"
          onclick={() => {
            extendTarget = null;
            extendNewExpiry = '';
          }}
          disabled={$extendMutation.isPending}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.common_cancel()}
        </button>
        <button
          type="button"
          data-testid="trusted-extend-submit"
          onclick={submitExtend}
          disabled={!extendNewExpiry || $extendMutation.isPending}
          class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.trusted_user_extend_submit_button()}
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- Edit-permissions modal -->
{#if editPermsTarget}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="trusted-edit-perms-modal-title"
    data-testid="trusted-edit-perms-modal"
  >
    <div class="w-full max-w-md overflow-y-auto rounded-lg bg-surface-card shadow-xl">
      <div class="border-b border-stone-200 px-6 py-4">
        <h2
          id="trusted-edit-perms-modal-title"
          class="m-0 text-lg font-semibold text-stone-900"
        >
          {m.trusted_user_edit_permissions_modal_title()}
        </h2>
      </div>
      <div class="space-y-4 p-6">
        <p class="m-0 text-sm leading-relaxed text-stone-700">
          {m.trusted_user_edit_permissions_modal_help()}
        </p>
        <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {#each ALL_TRUSTED_PERMISSIONS as perm (perm)}
            <label class="flex items-start gap-2 text-sm text-stone-700">
              <input
                data-testid={`trusted-edit-perms-${perm}`}
                type="checkbox"
                bind:checked={editPermsSelection[perm]}
                class="mt-0.5 h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500"
              />
              <span>{permissionLabel(perm)}</span>
            </label>
          {/each}
        </div>
      </div>
      <div class="flex justify-end gap-3 border-t border-stone-200 px-6 py-4">
        <button
          type="button"
          onclick={() => (editPermsTarget = null)}
          disabled={$editPermsMutation.isPending}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.common_cancel()}
        </button>
        <button
          type="button"
          data-testid="trusted-edit-perms-submit"
          onclick={submitEditPerms}
          disabled={editPermsSelectedList.length === 0 || $editPermsMutation.isPending}
          class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.trusted_user_edit_permissions_submit_button()}
        </button>
      </div>
    </div>
  </div>
{/if}
