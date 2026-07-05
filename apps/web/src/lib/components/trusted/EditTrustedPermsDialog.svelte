<script lang="ts">
  /**
   * Edit-permissions modal for a Trusted user (Owner-only, T520).
   *
   * Binds the per-permission selection record back to the parent, which
   * owns the update mutation and derives the granted list on submit.
   */
  import * as m from '$lib/paraglide/messages';
  import {
    ALL_TRUSTED_PERMISSIONS,
    permissionLabel,
    type TrustedPermissionRecord,
  } from './trustedPermissions';

  interface Props {
    selection: TrustedPermissionRecord;
    isPending: boolean;
    canSubmit: boolean;
    onSubmit: () => void;
    onCancel: () => void;
  }

  let {
    selection = $bindable(),
    isPending,
    canSubmit,
    onSubmit,
    onCancel,
  }: Props = $props();
</script>

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
              bind:checked={selection[perm]}
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
        onclick={onCancel}
        disabled={isPending}
        class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {m.common_cancel()}
      </button>
      <button
        type="button"
        data-testid="trusted-edit-perms-submit"
        onclick={onSubmit}
        disabled={!canSubmit || isPending}
        class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {m.trusted_user_edit_permissions_submit_button()}
      </button>
    </div>
  </div>
</div>
