<script lang="ts">
  /**
   * Project collaborators page (spec/011 US2/US3).
   *
   * Lets project managers issue member invitations — singly (T221) or in
   * bulk (T280) — list member-kind invitations and revoke pending ones
   * (T222). Each freshly-issued invitation URL is one-shot and
   * unrecoverable (T281): it lives only in transient `$state` (the reused
   * `InvitationUrlDialog` for single issue, the inline result table for
   * bulk) and is never persisted, logged, or carried in a listing row.
   *
   * Modeled on the sibling members page (manual `Promise.all` + `$state`
   * runes, no TanStack Query). Gating goes through the canonical
   * `manage_members` permission.
   *
   * This shell owns all data + handlers; the invite forms, bulk result
   * table and confirmation dialogs are extracted into
   * `$lib/components/collaborators/`.
   */

  import { page } from '$app/stores';
  import { projectsApi, buildInviteUrl } from '$lib/api/projects';
  import { ApiError } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import type {
    Project,
    ProjectInvitationListItem,
    ProjectMember,
    MemberInvitationRole,
    MemberInvitationIssueResponse,
    BulkInvitationResultItem,
  } from '$lib/types';
  import { authStore } from '$lib/stores/auth.svelte';
  import { buildProjectContext, can } from '$lib/utils/permissions';
  import InvitationUrlDialog from '$lib/components/InvitationUrlDialog.svelte';
  import SingleInviteForm from '$lib/components/collaborators/SingleInviteForm.svelte';
  import BulkInvitePanel from '$lib/components/collaborators/BulkInvitePanel.svelte';
  import RevokeInvitationDialog from '$lib/components/collaborators/RevokeInvitationDialog.svelte';
  import ReissueInvitationDialog from '$lib/components/collaborators/ReissueInvitationDialog.svelte';
  import {
    getInvitationStatusLabel,
    getInvitationStatusBadgeClass,
  } from '$lib/utils/statusFormatters';
  import * as m from '$lib/paraglide/messages';

  // Get project ID from URL
  const projectId = $derived($page.params.id!);

  // State
  let project = $state<Project | null>(null);
  let invitations = $state<ProjectInvitationListItem[]>([]);
  // Current members (#4): used to warn before inviting an email that
  // already belongs to an active member.
  let members = $state<ProjectMember[]>([]);
  let isLoading = $state(true);
  let error = $state<string | null>(null);

  // --- Single-invite form (T221) ---
  let inviteEmail = $state('');
  let inviteRole = $state<MemberInvitationRole>('member');
  let isIssuing = $state(false);
  let issueError = $state<string | null>(null);
  // One-shot URL dialog (T221 + T281): URL lives ONLY here, transient.
  let issuedUrl = $state<string | null>(null);

  // --- Bulk mode (T280) ---
  let bulkMode = $state(false);
  let bulkEmailsText = $state('');
  let bulkRole = $state<MemberInvitationRole>('member');
  let isBulkSubmitting = $state(false);
  let bulkError = $state<string | null>(null);
  // One-shot URLs (T281): transient result table, never persisted.
  let bulkResults = $state<BulkInvitationResultItem[] | null>(null);

  // --- Revoke confirmation (T222) ---
  let invitationToRevoke = $state<ProjectInvitationListItem | null>(null);
  let isRevoking = $state(false);

  // --- Revoke & re-issue (#6) ---
  // The one-shot token is hash-stored server-side and cannot be
  // re-displayed, so "re-share" is implemented as revoke + fresh issue.
  let invitationToReissue = $state<ProjectInvitationListItem | null>(null);
  let isReissuing = $state(false);
  let reissueError = $state<string | null>(null);
  // Tracks whether the revoke half of a revoke-&-re-issue has already
  // succeeded (H-1). On a retry after a partial failure (revoke ok, issue
  // failed) we must NOT re-revoke the now-revoked row (backend 404s an
  // already-revoked invitation) — we skip straight to the fresh issue.
  let revokeDone = $state(false);

  // Lowercase set of active member emails for the inline already-member
  // warning (#4). Recomputed whenever the members list changes.
  const memberEmails = $derived(
    new Set(members.map((mem) => mem.user.email.trim().toLowerCase()))
  );

  // True when the email currently typed in the single-invite form already
  // belongs to an active member.
  const inviteEmailIsMember = $derived(
    inviteEmail.trim().length > 0 && memberEmails.has(inviteEmail.trim().toLowerCase())
  );

  /**
   * Localized role of the active member matching `email`, or `null` when
   * none. Drives the role-aware already-member message.
   */
  function matchingMemberRoleLabel(email: string): string | null {
    const normalized = email.trim().toLowerCase();
    const match = members.find((mem) => mem.user.email.trim().toLowerCase() === normalized);
    if (!match) return null;
    return roleLabel(match.role);
  }

  // Localized already-member warning shown by the single-invite form, or
  // null when the typed email is not an active member.
  const alreadyMemberWarning = $derived.by(() => {
    if (!inviteEmailIsMember) return null;
    const roleText = matchingMemberRoleLabel(inviteEmail);
    return roleText
      ? m.collaborators_already_member_with_role({ role: roleText })
      : m.collaborators_already_member();
  });

  // Permission gating goes through the canonical `manage_members`
  // permission. This page does NOT use TanStack Query for its loads, so
  // the context is built directly via `buildProjectContext` rather than
  // the `usePermissionContext` store helper (same as the members page).
  const permissionContext = $derived(
    buildProjectContext({
      authStore: {
        isAuthenticated: authStore.isAuthenticated,
        user: authStore.user,
      },
      project: project ?? undefined,
      projectQueryState: { isLoading, isError: error !== null },
      pendingInvitationToken: null,
    })
  );
  const canManage = $derived(can('manage_members', permissionContext));

  /**
   * Load the project and its member-kind invitations.
   */
  async function loadData() {
    isLoading = true;
    error = null;

    try {
      const [projectData, invResponse, memberList] = await Promise.all([
        projectsApi.get(projectId),
        projectsApi.listInvitations(projectId, { kind: 'member' }),
        // Members feed the already-member warning (#4). A failure here is
        // non-fatal — fall back to an empty list rather than blocking the
        // whole page (the backend 409/bulk status still guard the submit).
        projectsApi.listMembers(projectId).catch(() => [] as ProjectMember[]),
      ]);

      project = projectData;
      invitations = invResponse.items;
      members = memberList;
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
        if (err.status === 404) {
          error = m.collaborators_error_not_found();
        } else if (err.status === 403) {
          error = m.collaborators_error_forbidden();
        }
      } else {
        error = m.collaborators_error_load();
      }
    } finally {
      isLoading = false;
    }
  }

  // Load data on mount
  $effect(() => {
    loadData();
  });

  /**
   * Toggle between single and bulk invite modes. Clears transient
   * per-mode state so switching does not leak a stale error or the
   * one-shot bulk result table.
   */
  function toggleBulkMode() {
    bulkMode = !bulkMode;
    issueError = null;
    bulkError = null;
    bulkResults = null;
  }

  /**
   * Issue a single invitation (T221). On success the one-shot URL is
   * surfaced via the reused dialog and the listing is refreshed so the
   * new pending row appears.
   */
  async function handleIssue(e: Event) {
    e.preventDefault();
    issueError = null;

    const email = inviteEmail.trim();
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      issueError = m.collaborators_error_invalid_email();
      return;
    }

    isIssuing = true;

    try {
      const res: MemberInvitationIssueResponse = await projectsApi.issueInvitation(projectId, {
        email,
        role: inviteRole,
      });
      // The backend returns a RAW signed token; build the full, shareable
      // URL against the admin's own browser origin (#5/#8).
      issuedUrl = buildInviteUrl(res.invitation_url); // open the one-shot dialog
      inviteEmail = '';
      inviteRole = 'member';
      await loadData(); // refresh listing so the new pending row appears
    } catch (err) {
      // #4: a 409 ERR_ALREADY_MEMBER means the email already belongs to an
      // active member — surface the friendly, role-aware message.
      if (err instanceof ApiError && err.status === 409 && err.code === 'ERR_ALREADY_MEMBER') {
        const roleText = matchingMemberRoleLabel(email);
        issueError = roleText
          ? m.collaborators_already_member_with_role({ role: roleText })
          : m.collaborators_already_member();
      } else {
        issueError =
          err instanceof ApiError ? err.detail || err.message : m.collaborators_error_issue();
      }
    } finally {
      isIssuing = false;
    }
  }

  /**
   * Issue invitations in bulk (T280). The result table (with one-shot
   * URLs) persists until navigation/toggle; we do NOT clear it on the
   * post-submit refresh.
   */
  async function handleBulkSubmit(e: Event) {
    e.preventDefault();
    bulkError = null;

    const parsed = bulkEmailsText
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    // Exact-duplicate dedupe: drops obvious paste mistakes that would
    // otherwise hit the backend's atomic in-list-duplicate rejection.
    const emails = [...new Set(parsed)];

    if (emails.length === 0) {
      bulkError = m.collaborators_bulk_error_empty();
      return;
    }
    if (emails.length > 50) {
      bulkError = m.collaborators_bulk_error_too_many();
      return;
    }

    isBulkSubmitting = true;

    try {
      bulkResults = await projectsApi.bulkInvite(projectId, { role: bulkRole, emails });
      bulkEmailsText = '';
      await loadData();
    } catch (err) {
      bulkError =
        err instanceof ApiError ? err.detail || err.message : m.collaborators_bulk_error_submit();
    } finally {
      isBulkSubmitting = false;
    }
  }

  /**
   * Show the revoke confirmation modal for a pending invitation (T222).
   */
  function showRevokeConfirmation(invitation: ProjectInvitationListItem) {
    invitationToRevoke = invitation;
  }

  /**
   * Cancel the revoke confirmation.
   */
  function cancelRevoke() {
    invitationToRevoke = null;
  }

  /**
   * Revoke the selected pending invitation. No reason is collected from
   * the UI. Any failure (including the anti-enumeration 404) surfaces as
   * a generic error.
   */
  async function confirmRevoke() {
    if (!invitationToRevoke) return;

    isRevoking = true;

    try {
      await projectsApi.revokeInvitation(projectId, invitationToRevoke.id);
      invitationToRevoke = null;
      await loadData();
    } catch (err) {
      error =
        err instanceof ApiError ? err.detail || err.message : m.collaborators_error_revoke();
    } finally {
      isRevoking = false;
    }
  }

  /**
   * Show the revoke-&-re-issue confirmation for a pending invitation (#6).
   */
  function showReissueConfirmation(invitation: ProjectInvitationListItem) {
    reissueError = null;
    // Opening the confirm for a (possibly new) target starts a fresh
    // revoke-&-re-issue cycle (H-1).
    revokeDone = false;
    invitationToReissue = invitation;
  }

  /**
   * Cancel the revoke-&-re-issue confirmation.
   */
  function cancelReissue() {
    if (isReissuing) return;
    invitationToReissue = null;
    reissueError = null;
    revokeDone = false;
  }

  /**
   * Revoke a pending invitation and immediately issue a fresh one with the
   * same email + role, then surface the NEW one-shot URL in the dialog (#6).
   *
   * The original token is hash-stored server-side and cannot be
   * re-displayed, so re-sharing necessarily mints a new invitation. We
   * revoke first (so the old link stops working) and issue second; the
   * listing is refreshed so the superseded row drops and the new pending
   * row appears.
   */
  async function confirmReissue() {
    const target = invitationToReissue;
    if (!target) return;

    // A non-member-role row (trusted kind) has no member role to re-issue.
    const role = target.role;
    if (!role) {
      reissueError = m.collaborators_error_reissue();
      return;
    }

    isReissuing = true;
    reissueError = null;

    try {
      // H-1: only revoke once. If a previous attempt revoked successfully
      // but the subsequent issue failed (429/5xx/409), retrying must skip
      // the revoke — the row is already revoked and the backend 404s it.
      if (!revokeDone) {
        await projectsApi.revokeInvitation(projectId, target.id);
        revokeDone = true;
      }
      const res: MemberInvitationIssueResponse = await projectsApi.issueInvitation(projectId, {
        email: target.bound_email,
        role,
      });
      invitationToReissue = null;
      revokeDone = false; // full success — reset for the next cycle
      issuedUrl = buildInviteUrl(res.invitation_url); // open the one-shot dialog
      await loadData(); // refresh listing (old row gone, new pending row in)
    } catch (err) {
      reissueError =
        err instanceof ApiError ? err.detail || err.message : m.collaborators_error_reissue();
      // M-1: refresh the listing so a successful-revoke/failed-issue partial
      // failure no longer shows the revoked row as `pending` with live
      // (now-404ing) buttons.
      await loadData();
    } finally {
      isReissuing = false;
    }
  }

  /**
   * Localized label for an invitation lifecycle status.
   */
  function statusLabel(status: string): string {
    return getInvitationStatusLabel(status, {
      pending: m.collaborators_status_pending,
      accepted: m.collaborators_status_accepted,
      declined: m.collaborators_status_declined,
      revoked: m.collaborators_status_revoked,
      expired: m.collaborators_status_expired,
    });
  }

  /**
   * Badge classes for an invitation lifecycle status.
   */
  function statusBadgeClass(status: string): string {
    return getInvitationStatusBadgeClass(status);
  }

  /**
   * Localized label for a member role (reuses the shared role keys).
   */
  function roleLabel(role: MemberInvitationRole | null): string {
    switch (role) {
      case 'viewer':
        return m.role_viewer();
      case 'admin':
        return m.role_admin();
      case 'member':
        return m.role_member();
      default:
        return '—';
    }
  }
</script>

<svelte:head>
  <title>{m.collaborators_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
  <!-- Header -->
  <div class="mb-8">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-3xl font-bold text-stone-900">{m.collaborators_heading()}</h1>
        <p class="mt-2 text-sm text-stone-600">{m.collaborators_description()}</p>
      </div>
      <a
        href={localizeHref(`/projects/${projectId}`)}
        class="text-sm font-medium text-primary-600 hover:text-primary-500"
      >
        {m.collaborators_back_to_project()}
      </a>
    </div>
  </div>

  <!-- Loading State -->
  {#if isLoading}
    <div class="flex items-center justify-center py-12">
      <svg
        class="h-8 w-8 animate-spin text-primary-600"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
        ></circle>
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        ></path>
      </svg>
    </div>
  {:else if !canManage}
    <!-- Access Denied (all-or-nothing: no form, no listing) -->
    <div class="rounded-md bg-danger-light p-4" role="alert">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg
            class="h-5 w-5 text-danger"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fill-rule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
              clip-rule="evenodd"
            />
          </svg>
        </div>
        <div class="ml-3">
          <p class="text-sm font-medium text-danger">
            {m.collaborators_access_denied()}
          </p>
        </div>
      </div>
    </div>
  {:else}
    <!-- Error Message -->
    {#if error}
      <div class="mb-6 rounded-md bg-danger-light p-4" role="alert">
        <div class="flex">
          <div class="flex-shrink-0">
            <svg
              class="h-5 w-5 text-danger"
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fill-rule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                clip-rule="evenodd"
              />
            </svg>
          </div>
          <div class="ml-3">
            <p class="text-sm font-medium text-danger">{error}</p>
          </div>
        </div>
      </div>
    {/if}

    <!-- Invite Section -->
    <div class="mb-6 rounded-lg bg-surface-card shadow">
      <div class="p-6">
        <!-- Mode toggle -->
        <div class="mb-6 inline-flex rounded-md border border-stone-300 p-0.5">
          <button
            type="button"
            onclick={() => !bulkMode || toggleBulkMode()}
            class="rounded px-3 py-1.5 text-sm font-medium {!bulkMode
              ? 'bg-primary-600 text-white dark:bg-primary-500 dark:text-stone-50'
              : 'text-stone-700 hover:bg-stone-50'}"
          >
            {m.collaborators_bulk_toggle_single()}
          </button>
          <button
            type="button"
            onclick={() => bulkMode || toggleBulkMode()}
            class="rounded px-3 py-1.5 text-sm font-medium {bulkMode
              ? 'bg-primary-600 text-white dark:bg-primary-500 dark:text-stone-50'
              : 'text-stone-700 hover:bg-stone-50'}"
          >
            {m.collaborators_bulk_toggle_bulk()}
          </button>
        </div>

        {#if !bulkMode}
          <SingleInviteForm
            bind:email={inviteEmail}
            bind:role={inviteRole}
            {isIssuing}
            {issueError}
            emailIsMember={inviteEmailIsMember}
            {alreadyMemberWarning}
            onSubmit={handleIssue}
          />
        {:else}
          <BulkInvitePanel
            bind:emailsText={bulkEmailsText}
            bind:role={bulkRole}
            isSubmitting={isBulkSubmitting}
            submitError={bulkError}
            results={bulkResults}
            onSubmit={handleBulkSubmit}
          />
        {/if}
      </div>
    </div>

    <!-- Invitation Listing (T222) -->
    <div class="rounded-lg bg-surface-card shadow">
      <div class="p-6">
        <h2 class="mb-4 text-lg font-semibold text-stone-900">
          {m.collaborators_list_heading()}
        </h2>

        {#if invitations.length === 0}
          <p class="py-4 text-sm text-stone-500">{m.collaborators_list_empty()}</p>
        {:else}
          <div class="overflow-x-auto">
            <table class="w-full text-left">
              <thead>
                <tr class="border-b border-stone-200 bg-stone-50">
                  <th class="px-4 py-2 text-sm font-medium text-stone-700"
                    >{m.collaborators_list_col_email()}</th
                  >
                  <th class="px-4 py-2 text-sm font-medium text-stone-700"
                    >{m.collaborators_list_col_role()}</th
                  >
                  <th class="px-4 py-2 text-sm font-medium text-stone-700"
                    >{m.collaborators_list_col_status()}</th
                  >
                  <th class="px-4 py-2 text-sm font-medium text-stone-700"
                    >{m.collaborators_list_col_issued()}</th
                  >
                  <th class="px-4 py-2 text-sm font-medium text-stone-700"
                    >{m.collaborators_list_col_expires()}</th
                  >
                  <th class="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {#each invitations as invitation (invitation.id)}
                  <tr class="border-b border-stone-200 hover:bg-stone-50">
                    <td class="px-4 py-2 text-sm text-stone-700">{invitation.bound_email}</td>
                    <td class="px-4 py-2 text-sm text-stone-700">{roleLabel(invitation.role)}</td>
                    <td class="px-4 py-2 text-sm">
                      <span
                        class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium {statusBadgeClass(
                          invitation.status
                        )}"
                      >
                        {statusLabel(invitation.status)}
                      </span>
                    </td>
                    <td class="px-4 py-2 text-sm text-stone-700">
                      {new Date(invitation.issued_at).toLocaleDateString()}
                    </td>
                    <td class="px-4 py-2 text-sm text-stone-700">
                      {new Date(invitation.expires_at).toLocaleDateString()}
                    </td>
                    <td class="px-4 py-2 text-right text-sm">
                      {#if invitation.status === 'pending'}
                        <div class="flex items-center justify-end gap-2">
                          <button
                            type="button"
                            onclick={() => showReissueConfirmation(invitation)}
                            class="rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm font-medium text-stone-700 hover:bg-stone-50"
                            data-testid="reissue-invitation-button"
                          >
                            {m.collaborators_reissue_button()}
                          </button>
                          <button
                            type="button"
                            onclick={() => showRevokeConfirmation(invitation)}
                            class="rounded-md border border-danger/30 bg-surface-card px-3 py-1.5 text-sm font-medium text-danger hover:bg-danger-light"
                          >
                            {m.collaborators_revoke_button()}
                          </button>
                        </div>
                      {/if}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>

<!-- One-shot invitation URL dialog (T221 + T281) -->
<InvitationUrlDialog
  open={issuedUrl !== null}
  url={issuedUrl ?? ''}
  onClose={() => (issuedUrl = null)}
/>

<!-- Revoke Confirmation Dialog (T222) -->
{#if invitationToRevoke}
  <RevokeInvitationDialog
    invitation={invitationToRevoke}
    {isRevoking}
    onConfirm={confirmRevoke}
    onCancel={cancelRevoke}
  />
{/if}

<!-- Revoke & re-issue Confirmation Dialog (#6) -->
{#if invitationToReissue}
  <ReissueInvitationDialog
    invitation={invitationToReissue}
    {isReissuing}
    {reissueError}
    onConfirm={confirmReissue}
    onCancel={cancelReissue}
  />
{/if}
