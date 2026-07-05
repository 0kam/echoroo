<script lang="ts">
  /**
   * Revoke-&-re-issue confirmation dialog for a pending invitation (#6).
   *
   * The original one-shot token is hash-stored server-side and cannot be
   * re-displayed, so re-sharing revokes the old invitation and mints a new
   * one. The parent owns that two-step flow and surfaces any partial-failure
   * error via `reissueError`.
   */
  import type { ProjectInvitationListItem } from '$lib/types';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    invitation: ProjectInvitationListItem;
    isReissuing: boolean;
    reissueError: string | null;
    onConfirm: () => void;
    onCancel: () => void;
  }

  let { invitation, isReissuing, reissueError, onConfirm, onCancel }: Props = $props();
</script>

<div class="fixed inset-0 z-50 overflow-y-auto" role="dialog">
  <div
    class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0"
  >
    <!-- Background overlay -->
    <div
      role="button"
      tabindex="0"
      aria-label={m.common_close_dialog()}
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
            class="mx-auto flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-warning-light sm:mx-0 sm:h-10 sm:w-10"
          >
            <svg
              class="h-6 w-6 text-warning"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
          </div>
          <div class="mt-3 text-center sm:ml-4 sm:mt-0 sm:text-left">
            <h3 class="text-lg font-medium leading-6 text-stone-900">
              {m.collaborators_reissue_confirm_title()}
            </h3>
            <div class="mt-2 space-y-2">
              <p class="text-sm text-stone-500">
                {m.collaborators_reissue_confirm_message({
                  email: invitation.bound_email,
                })}
              </p>
              <p class="text-sm font-medium text-warning">
                {m.collaborators_reissue_confirm_warning()}
              </p>
              {#if reissueError}
                <p class="text-sm text-danger" data-testid="reissue-error">{reissueError}</p>
              {/if}
            </div>
          </div>
        </div>
      </div>
      <div class="bg-stone-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
        <button
          type="button"
          onclick={onConfirm}
          disabled={isReissuing}
          class="inline-flex w-full justify-center rounded-md bg-primary-600 px-4 py-2 text-base font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400 sm:ml-3 sm:w-auto sm:text-sm"
          data-testid="reissue-confirm-button"
        >
          {isReissuing
            ? m.collaborators_reissuing()
            : m.collaborators_reissue_confirm_button()}
        </button>
        <button
          type="button"
          onclick={onCancel}
          disabled={isReissuing}
          class="mt-3 inline-flex w-full justify-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-base font-medium text-stone-700 shadow-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
        >
          {m.collaborators_revoke_cancel()}
        </button>
      </div>
    </div>
  </div>
</div>
