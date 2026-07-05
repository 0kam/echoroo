<script lang="ts">
  /**
   * Extend-expiry modal for a Trusted user (Owner-only, T520).
   *
   * Binds the `datetime-local` expiry field back to the parent, which owns
   * the update mutation and the ISO conversion on submit.
   */
  import * as m from '$lib/paraglide/messages';

  interface Props {
    newExpiry: string;
    isPending: boolean;
    onSubmit: () => void;
    onCancel: () => void;
  }

  let {
    newExpiry = $bindable(),
    isPending,
    onSubmit,
    onCancel,
  }: Props = $props();
</script>

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
          bind:value={newExpiry}
          class="mt-1 block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500"
        />
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
        data-testid="trusted-extend-submit"
        onclick={onSubmit}
        disabled={!newExpiry || isPending}
        class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {m.trusted_user_extend_submit_button()}
      </button>
    </div>
  </div>
</div>
