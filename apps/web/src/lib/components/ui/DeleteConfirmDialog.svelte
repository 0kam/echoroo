<script lang="ts">
  import * as m from '$lib/paraglide/messages';

  let {
    isOpen = false,
    title = 'Confirm Delete',
    message = 'Are you sure you want to delete this item?',
    warnings = [] as string[],
    confirmText = 'Delete',
    isDeleting = false,
    onConfirm,
    onCancel,
  }: {
    isOpen?: boolean;
    title?: string;
    message?: string;
    warnings?: string[];
    confirmText?: string;
    isDeleting?: boolean;
    onConfirm: () => void;
    onCancel: () => void;
  } = $props();
</script>

{#if isOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-overlay" onclick={onCancel}>
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="modal" onclick={(e) => e.stopPropagation()}>
      <h3 class="modal-title">{title}</h3>
      <p class="modal-message">{message}</p>

      {#if warnings.length > 0}
        <div class="warning-box">
          <p class="warning-title">{m.delete_dialog_warning_title()}</p>
          <ul class="warning-list">
            {#each warnings as warning}
              <li>{warning}</li>
            {/each}
          </ul>
        </div>
      {/if}

      <div class="modal-actions">
        <button
          type="button"
          onclick={onCancel}
          disabled={isDeleting}
          class="btn-cancel"
        >
          Cancel
        </button>
        <button
          type="button"
          onclick={onConfirm}
          disabled={isDeleting}
          class="btn-confirm"
        >
          {isDeleting ? 'Deleting...' : confirmText}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: 1rem;
  }

  .modal {
    background: rgb(var(--color-card-bg));
    border-radius: 0.5rem;
    padding: 1.5rem;
    max-width: 28rem;
    width: 100%;
    margin: 0 1rem;
  }

  .modal-title {
    font-size: 1.125rem;
    font-weight: 600;
    color: rgb(var(--color-danger));
    margin: 0 0 0.5rem 0;
  }

  .modal-message {
    color: #57534e;
    margin: 0 0 1rem 0;
    line-height: 1.5;
  }

  .warning-box {
    background: rgb(var(--color-warning-light));
    border: 1px solid rgb(var(--color-warning));
    border-radius: 0.5rem;
    padding: 0.75rem;
    margin-bottom: 1rem;
  }

  .warning-title {
    font-size: 0.875rem;
    font-weight: 500;
    color: rgb(var(--color-warning));
    margin: 0 0 0.5rem 0;
  }

  .warning-list {
    font-size: 0.875rem;
    color: rgb(var(--color-warning));
    margin: 0;
    padding-left: 1.25rem;
    list-style-type: disc;
  }

  .warning-list li {
    margin: 0.25rem 0;
  }

  .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
  }

  .btn-cancel,
  .btn-confirm {
    padding: 0.5rem 1rem;
    font-size: 0.875rem;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .btn-cancel {
    background: rgb(var(--color-card-bg));
    color: rgb(var(--stone-700));
    border: 1px solid #d6d3d1;
  }

  .btn-cancel:hover:not(:disabled) {
    background: #fafaf9;
  }

  .btn-cancel:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-confirm {
    background: rgb(var(--color-danger));
    color: white;
    border: none;
  }

  .btn-confirm:hover:not(:disabled) {
    opacity: 0.9;
  }

  .btn-confirm:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
