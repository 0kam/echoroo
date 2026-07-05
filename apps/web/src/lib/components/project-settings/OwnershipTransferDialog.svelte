<script lang="ts">
  /**
   * OwnershipTransferDialog — owner-only ownership-transfer flow.
   *
   * Extracted from the project settings page (preview feedback #2 /
   * SU-bootstrap redesign). Encapsulates the full flow: lazy member loading,
   * the eligible-Admin picker, and the danger-styled confirmation modal.
   *
   * Members are loaded lazily once the caller is confirmed to be the owner
   * (the listing endpoint is admin-gated). Eligible transfer targets are the
   * project's active Admins — the backend rejects any other target with
   * `ERR_INVALID_TRANSFER_TARGET`.
   *
   * After a successful transfer the parent is asked to reload the project via
   * {@link Props.onTransferred}; once the caller is demoted to Admin the
   * `isOwner` prop flips false and this component renders nothing.
   */
  import { ApiError } from '$lib/api/client';
  import { projectsApi } from '$lib/api/projects';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { ProjectMember } from '$lib/types';

  interface Props {
    projectId: string;
    /** Whether the current caller owns the project. */
    isOwner: boolean;
    /**
     * Reload the project after a transfer settles (success / conflict). The
     * parent's reload flips `owner.id` + `current_user_role`, which in turn
     * flips `isOwner` false and unmounts this component.
     */
    onTransferred: () => void | Promise<void>;
  }

  const { projectId, isOwner, onTransferred }: Props = $props();

  // Members loaded lazily for the transfer picker.
  let members = $state<ProjectMember[]>([]);
  let membersLoading = $state(false);
  let membersError = $state<string | null>(null);
  // "Loaded" latch for the lazy auto-load effect. The OWNER is not stored as a
  // `project_members` row, so a freshly-created project legitimately returns an
  // empty list — we cannot infer "done" from `members.length`, or the effect
  // would re-fire forever. This latch is set once `loadMembers()` settles
  // (even on an empty result) and gates only the auto-load effect, never the
  // direct error-recovery refetches in `confirmTransfer`.
  let membersLoaded = $state(false);
  let selectedNewOwnerId = $state('');
  // Confirmation dialog target (the chosen Admin member) — drives the
  // danger-styled confirm modal. `null` = dialog closed.
  let transferTarget = $state<ProjectMember | null>(null);
  let isTransferring = $state(false);
  // Error surfaced inside the transfer section / dialog (never console-only).
  let transferError = $state<string | null>(null);
  let transferSuccess = $state<string | null>(null);

  // Eligible transfer targets: active project Admins. The backend only
  // permits transferring ownership to an active Admin, so we filter the
  // member list to `role === 'admin'` and never offer Members/Viewers or
  // the owner themselves.
  const eligibleAdmins = $derived(members.filter((mem) => mem.role === 'admin'));

  // Currently-selected target member resolved from the picker value.
  const selectedNewOwner = $derived<ProjectMember | null>(
    selectedNewOwnerId === ''
      ? null
      : (eligibleAdmins.find((mem) => mem.user.id === selectedNewOwnerId) ?? null)
  );

  /**
   * Display label for a member in the picker: `display_name (email)`,
   * falling back to just the email when no display name is set.
   */
  function memberLabel(mem: ProjectMember): string {
    const name = mem.user.display_name?.trim();
    return name ? `${name} (${mem.user.email})` : mem.user.email;
  }

  /**
   * Load the project's members for the transfer picker. Called lazily once
   * the caller is confirmed to be the owner (the listing endpoint is
   * admin-gated, so a non-owner Admin could still load it, but we only ever
   * surface the picker to the owner).
   */
  async function loadMembers() {
    membersLoading = true;
    membersError = null;
    try {
      members = await projectsApi.listMembers(projectId);
    } catch (err) {
      if (err instanceof ApiError) {
        membersError = err.detail || err.message;
      } else {
        membersError = m.project_transfer_members_load_error();
      }
    } finally {
      membersLoading = false;
      // Latch as loaded even when the result is an empty array (owner-only
      // project), so the auto-load effect below settles instead of looping.
      membersLoaded = true;
    }
  }

  // Load members once we know the caller is the owner. `$effect` re-runs when
  // `isOwner` flips true after the project finishes loading. Gated on the
  // `membersLoaded` latch (not `members.length`) so an empty member list — the
  // expected case for a freshly-created project whose only role is the owner —
  // is a terminal state, not an infinite re-fetch.
  $effect(() => {
    if (isOwner && !membersLoaded && !membersLoading && membersError === null) {
      loadMembers();
    }
  });

  /**
   * Open the confirmation dialog for the currently-selected Admin target.
   */
  function openTransferConfirm() {
    transferError = null;
    if (selectedNewOwner) {
      transferTarget = selectedNewOwner;
    }
  }

  /**
   * Close / cancel the transfer confirmation dialog.
   */
  function cancelTransfer() {
    if (isTransferring) return;
    transferTarget = null;
  }

  /**
   * Confirm and perform the ownership transfer.
   *
   * Generates a fresh UUID v4 idempotency key per attempt so a double-click
   * inside the dialog cannot transfer twice. On success the project +
   * members are reloaded; once the caller is demoted to Admin, `isOwner`
   * flips false and the whole transfer section disappears.
   */
  async function confirmTransfer() {
    if (!transferTarget) return;

    isTransferring = true;
    transferError = null;
    const target = transferTarget;

    try {
      const idempotencyKey = crypto.randomUUID();
      await projectsApi.transferOwnership(projectId, target.user.id, idempotencyKey);

      // Reflect the new ownership: reload the project (so `owner.id` +
      // `current_user_role` update and `isOwner` flips false) and the
      // member list. The transfer UI disappears since the caller is now an
      // Admin, not the Owner.
      transferTarget = null;
      selectedNewOwnerId = '';
      transferSuccess = m.project_transfer_success({ name: memberLabel(target) });
      await Promise.all([onTransferred(), loadMembers()]);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 400 || err.code === 'ERR_INVALID_TRANSFER_TARGET') {
          // Target is no longer an active Admin — refresh the picker so the
          // stale option drops out, and ask the owner to pick another.
          transferError = m.project_transfer_error_invalid_target();
          await loadMembers();
        } else if (err.status === 409) {
          // Idempotency / concurrent-transfer conflict. The transfer most
          // likely already applied (or another tab raced it); reload to
          // reflect the authoritative state and let the owner retry if not.
          transferError = m.project_transfer_error_conflict();
          await Promise.all([onTransferred(), loadMembers()]);
        } else {
          transferError = err.detail || err.message || m.project_transfer_error_generic();
        }
      } else {
        transferError = m.project_transfer_error_generic();
      }
    } finally {
      isTransferring = false;
    }
  }
</script>

<!-- Transfer ownership (preview feedback #2 / SU-bootstrap redesign).
     Owner-only, danger-styled. Eligible targets are active project
     Admins; the section disappears once the caller is no longer the
     owner (after a successful transfer they become an Admin). -->
{#if isOwner}
  <div class="mt-8 rounded-lg border border-danger/30 bg-surface-card shadow">
    <div class="space-y-4 p-6">
      <div>
        <h2 class="text-lg font-semibold text-danger">
          {m.project_transfer_heading()}
        </h2>
        <p class="mt-1 text-sm text-stone-600">
          {m.project_transfer_description()}
        </p>
      </div>

      <!-- Transfer success -->
      {#if transferSuccess}
        <div class="rounded-md bg-success-light p-3" role="status">
          <p class="text-sm font-medium text-success">{transferSuccess}</p>
        </div>
      {/if}

      <!-- Transfer error (section-level; dialog also surfaces it) -->
      {#if transferError}
        <div class="rounded-md bg-danger-light p-3" role="alert">
          <p class="text-sm font-medium text-danger">{transferError}</p>
        </div>
      {/if}

      {#if membersLoading}
        <p class="text-sm text-stone-500">{m.project_transfer_members_loading()}</p>
      {:else if membersError}
        <p class="text-sm text-danger" role="alert">{membersError}</p>
      {:else if eligibleAdmins.length === 0}
        <!-- No eligible Admins: hint to invite one first. -->
        <div class="rounded-md bg-warning-light p-3">
          <p class="text-sm text-stone-700">{m.project_transfer_no_admins_hint()}</p>
          <a
            href={localizeHref(`/projects/${projectId}/collaborators`)}
            class="mt-1 inline-block text-sm font-medium text-primary-600 hover:text-primary-500"
          >
            {m.project_transfer_go_to_collaborators()}
          </a>
        </div>
      {:else}
        <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div class="flex-1">
            <label for="transfer-target" class="block text-sm font-medium text-stone-700">
              {m.project_transfer_select_label()}
            </label>
            <select
              id="transfer-target"
              bind:value={selectedNewOwnerId}
              disabled={isTransferring}
              data-testid="transfer-owner-select"
              class="mt-1 block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed"
            >
              <option value="" disabled>{m.project_transfer_select_placeholder()}</option>
              {#each eligibleAdmins as admin (admin.user.id)}
                <option value={admin.user.id}>{memberLabel(admin)}</option>
              {/each}
            </select>
          </div>
          <button
            type="button"
            onclick={openTransferConfirm}
            disabled={isTransferring || selectedNewOwnerId === ''}
            data-testid="transfer-owner-button"
            class="inline-flex items-center justify-center rounded-md bg-danger px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-danger/50 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {m.project_transfer_button()}
          </button>
        </div>
      {/if}
    </div>
  </div>
{/if}

<!-- Transfer ownership confirmation dialog (danger-styled). -->
{#if transferTarget}
  <div class="fixed inset-0 z-50 overflow-y-auto" role="dialog" aria-modal="true">
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        role="button"
        tabindex="0"
        aria-label={m.project_transfer_cancel()}
        class="fixed inset-0 bg-stone-500 bg-opacity-75 transition-opacity"
        onclick={cancelTransfer}
        onkeydown={(e) => e.key === 'Escape' && cancelTransfer()}
      ></div>

      <!-- Modal panel -->
      <div
        class="inline-block transform overflow-hidden rounded-lg bg-surface-card text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle"
      >
        <div class="bg-surface-card px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <div class="sm:flex sm:items-start">
            <div
              class="mx-auto flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-danger-light sm:mx-0 sm:h-10 sm:w-10"
            >
              <svg class="h-6 w-6 text-danger" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
            </div>
            <div class="mt-3 text-center sm:ml-4 sm:mt-0 sm:text-left">
              <h3 class="text-lg font-medium leading-6 text-stone-900">
                {m.project_transfer_confirm_title()}
              </h3>
              <div class="mt-2">
                <p class="text-sm text-stone-500">
                  {m.project_transfer_confirm_body({ name: memberLabel(transferTarget) })}
                </p>
              </div>
              {#if transferError}
                <p class="mt-3 text-sm text-danger" role="alert">{transferError}</p>
              {/if}
            </div>
          </div>
        </div>
        <div class="bg-stone-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={confirmTransfer}
            disabled={isTransferring}
            data-testid="transfer-owner-confirm"
            class="inline-flex w-full justify-center rounded-md bg-danger px-4 py-2 text-base font-medium text-white shadow-sm hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-danger/50 focus:ring-offset-2 disabled:opacity-50 sm:ml-3 sm:w-auto sm:text-sm"
          >
            {isTransferring
              ? m.project_transfer_confirming()
              : m.project_transfer_confirm_submit()}
          </button>
          <button
            type="button"
            onclick={cancelTransfer}
            disabled={isTransferring}
            class="mt-3 inline-flex w-full justify-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-base font-medium text-stone-700 shadow-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
          >
            {m.project_transfer_cancel()}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
