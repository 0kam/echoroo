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
   * This shell owns all data + mutations; the invite form, list and the
   * three confirmation modals are extracted into
   * `$lib/components/trusted/`.
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
  import { localizeHref } from '$lib/paraglide/runtime';
  import type {
    Project,
    ProjectTrustedStatus,
    TrustedUser,
    TrustedUserInviteRequest,
    TrustedUserListResponse,
    TrustedUserUpdateRequest,
  } from '$lib/types';
  import TrustedInviteForm from '$lib/components/trusted/TrustedInviteForm.svelte';
  import TrustedUserList from '$lib/components/trusted/TrustedUserList.svelte';
  import RevokeTrustedDialog from '$lib/components/trusted/RevokeTrustedDialog.svelte';
  import ExtendTrustedDialog from '$lib/components/trusted/ExtendTrustedDialog.svelte';
  import EditTrustedPermsDialog from '$lib/components/trusted/EditTrustedPermsDialog.svelte';
  import {
    defaultInvitePermissionRecord,
    permissionRecordFrom,
    selectedPermissions,
    type TrustedFlash,
    type TrustedPermissionRecord,
  } from '$lib/components/trusted/trustedPermissions';

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

  let inviteEmail = $state('');
  let invitePermissions = $state<TrustedPermissionRecord>(
    defaultInvitePermissionRecord(),
  );
  /** Default 90 days, hard-capped at 365 (FR-043). */
  let inviteDurationSeconds = $state<number>(90 * 24 * 3600);
  let inviteFlash = $state<TrustedFlash>({ kind: 'idle' });

  const inviteSelectedPermissions = $derived(
    selectedPermissions(invitePermissions),
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

  let rowFlash = $state<TrustedFlash>({ kind: 'idle' });

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
  let editPermsSelection = $state<TrustedPermissionRecord>(
    permissionRecordFrom([]),
  );

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
    editPermsSelection = permissionRecordFrom(row.granted_permissions);
    rowFlash = { kind: 'idle' };
  }

  const editPermsSelectedList = $derived(
    selectedPermissions(editPermsSelection),
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
      <TrustedInviteForm
        bind:email={inviteEmail}
        bind:permissions={invitePermissions}
        bind:durationSeconds={inviteDurationSeconds}
        flash={inviteFlash}
        isPending={$inviteMutation.isPending}
        canSubmit={inviteFormValid}
        onSubmit={submitInvite}
      />
    {/if}

    <!-- Trusted Users list ------------------------------------------- -->
    <TrustedUserList
      bind:statusFilter
      {rowFlash}
      isLoading={$trustedListQuery.isLoading}
      isError={$trustedListQuery.isError}
      items={trustedItems}
      {isAdmin}
      {isOwner}
      onExtend={openExtendModal}
      onEditPerms={openEditPermsModal}
      onRevoke={openRevokeModal}
    />
  {/if}
</div>

<!-- Revoke confirmation modal -->
{#if revokeTarget}
  <RevokeTrustedDialog
    isPending={$revokeMutation.isPending}
    onConfirm={confirmRevoke}
    onCancel={() => (revokeTarget = null)}
  />
{/if}

<!-- Extend modal -->
{#if extendTarget}
  <ExtendTrustedDialog
    bind:newExpiry={extendNewExpiry}
    isPending={$extendMutation.isPending}
    onSubmit={submitExtend}
    onCancel={() => {
      extendTarget = null;
      extendNewExpiry = '';
    }}
  />
{/if}

<!-- Edit-permissions modal -->
{#if editPermsTarget}
  <EditTrustedPermsDialog
    bind:selection={editPermsSelection}
    isPending={$editPermsMutation.isPending}
    canSubmit={editPermsSelectedList.length > 0}
    onSubmit={submitEditPerms}
    onCancel={() => (editPermsTarget = null)}
  />
{/if}
