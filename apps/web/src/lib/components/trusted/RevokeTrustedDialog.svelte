<script lang="ts">
  /**
   * Revoke confirmation modal for a Trusted user (Owner-only, T520).
   *
   * The parent only renders this when a target row is selected. Confirm /
   * cancel are delegated up; the parent owns the revoke mutation.
   */
  import * as m from '$lib/paraglide/messages';

  interface Props {
    isPending: boolean;
    onConfirm: () => void;
    onCancel: () => void;
  }

  let { isPending, onConfirm, onCancel }: Props = $props();
</script>

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
        onclick={onCancel}
        disabled={isPending}
        class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {m.common_cancel()}
      </button>
      <button
        type="button"
        data-testid="trusted-revoke-confirm"
        onclick={onConfirm}
        disabled={isPending}
        class="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {m.trusted_user_revoke_confirm_button()}
      </button>
    </div>
  </div>
</div>
