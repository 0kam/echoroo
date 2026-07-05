<script lang="ts">
  /**
   * Revoke confirmation dialog for a pending member invitation (T222).
   *
   * The parent only renders this when a target invitation is selected, so
   * `invitation` is always present. Confirm / cancel are delegated up.
   */
  import type { ProjectInvitationListItem } from '$lib/types';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    invitation: ProjectInvitationListItem;
    isRevoking: boolean;
    onConfirm: () => void;
    onCancel: () => void;
  }

  let { invitation, isRevoking, onConfirm, onCancel }: Props = $props();
</script>

<div class="fixed inset-0 z-50 overflow-y-auto" role="dialog">
  <div
    class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0"
  >
    <!-- Background overlay -->
    <div
      role="button"
      tabindex="0"
      aria-label="Close dialog"
      class="fixed inset-0 bg-stone-500 bg-opacity-75 transition-opacity"
      onclick={onCancel}
      onkeydown={(e) => e.key === 'Escape' && onCancel()}
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
            <svg
              class="h-6 w-6 text-danger"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
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
              {m.collaborators_revoke_confirm_title()}
            </h3>
            <div class="mt-2">
              <p class="text-sm text-stone-500">
                {m.collaborators_revoke_confirm_message({
                  email: invitation.bound_email,
                })}
              </p>
            </div>
          </div>
        </div>
      </div>
      <div class="bg-stone-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
        <button
          type="button"
          onclick={onConfirm}
          disabled={isRevoking}
          class="inline-flex w-full justify-center rounded-md bg-danger px-4 py-2 text-base font-medium text-white shadow-sm hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-danger/50 focus:ring-offset-2 disabled:opacity-50 sm:ml-3 sm:w-auto sm:text-sm"
        >
          {isRevoking ? m.collaborators_revoking() : m.collaborators_revoke_confirm_button()}
        </button>
        <button
          type="button"
          onclick={onCancel}
          disabled={isRevoking}
          class="mt-3 inline-flex w-full justify-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-base font-medium text-stone-700 shadow-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
        >
          {m.collaborators_revoke_cancel()}
        </button>
      </div>
    </div>
  </div>
</div>
