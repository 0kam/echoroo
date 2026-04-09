<script lang="ts">
  import * as m from '$lib/paraglide/messages';

  interface Props {
    isOpen?: boolean;
    title: string;
    message: string;
    confirmText?: string;
    cancelText?: string;
    isDanger?: boolean;
    onConfirm: () => void | Promise<void>;
    onCancel?: () => void;
    warningItems?: string[];
    errorMessage?: string | null;
  }

  let {
    isOpen = false,
    title,
    message,
    confirmText = 'Confirm',
    cancelText = 'Cancel',
    isDanger = false,
    onConfirm,
    onCancel = () => {},
    warningItems = [],
    errorMessage = null,
  }: Props = $props();

  let isProcessing = $state(false);

  async function handleConfirm() {
    isProcessing = true;
    try {
      await onConfirm();
    } finally {
      isProcessing = false;
    }
  }

  function handleCancel() {
    if (!isProcessing) {
      onCancel();
    }
  }

  function handleBackdropClick(event: MouseEvent) {
    if (event.target === event.currentTarget) {
      handleCancel();
    }
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && !isProcessing) {
      handleCancel();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if isOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    onclick={handleBackdropClick}
    role="dialog"
    aria-modal="true"
    aria-labelledby="confirm-dialog-title"
    tabindex="-1"
  >
    <div class="w-full max-w-md overflow-y-auto rounded-lg bg-surface-card shadow-xl">
      <!-- Header -->
      <div class="border-b border-stone-200 px-6 py-4">
        <h2 id="confirm-dialog-title" class="m-0 text-lg font-semibold text-stone-900">{title}</h2>
      </div>

      <!-- Body -->
      <div class="p-6">
        <p class="m-0 mb-4 leading-relaxed text-stone-700">{message}</p>

        {#if warningItems.length > 0}
          <div class="rounded-md border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-900/20">
            <div class="mb-3 flex items-center gap-2">
              <svg class="h-5 w-5 flex-shrink-0 text-red-600 dark:text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path
                  d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
                  stroke-width="2"
                />
                <line x1="12" y1="9" x2="12" y2="13" stroke-width="2" />
                <line x1="12" y1="17" x2="12.01" y2="17" stroke-width="2" />
              </svg>
              <span class="text-sm font-medium text-red-800 dark:text-red-400">{m.common_delete_warning_items()}</span>
            </div>
            <ul class="m-0 pl-6 text-sm text-red-900 dark:text-red-300">
              {#each warningItems as item}
                <li class="mb-1">{item}</li>
              {/each}
            </ul>
          </div>
        {/if}

        {#if errorMessage}
          <div class="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
            {errorMessage}
          </div>
        {/if}
      </div>

      <!-- Footer -->
      <div class="flex justify-end gap-3 border-t border-stone-200 px-6 py-4">
        <button
          type="button"
          onclick={handleCancel}
          disabled={isProcessing}
          class="rounded-md border border-stone-300 bg-surface-card px-5 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {cancelText}
        </button>
        <button
          type="button"
          onclick={handleConfirm}
          disabled={isProcessing}
          class="rounded-md px-5 py-2 text-sm font-medium text-white transition-colors disabled:cursor-not-allowed disabled:opacity-50
            {isDanger ? 'bg-red-600 hover:bg-red-700' : 'bg-primary-600 hover:bg-primary-700'}"
        >
          {isProcessing ? m.common_processing() : confirmText}
        </button>
      </div>
    </div>
  </div>
{/if}
