<script lang="ts">
  export let isOpen: boolean = false;
  export let title: string = 'Confirm Delete';
  export let message: string = 'Are you sure you want to delete this item?';
  export let warnings: string[] = [];
  export let confirmText: string = 'Delete';
  export let isDeleting: boolean = false;
  export let onConfirm: () => void;
  export let onCancel: () => void;
</script>

{#if isOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-overlay" on:click={onCancel}>
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="modal" on:click|stopPropagation>
      <h3 class="modal-title">{title}</h3>
      <p class="modal-message">{message}</p>

      {#if warnings.length > 0}
        <div class="warning-box">
          <p class="warning-title">Warning: This will also delete:</p>
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
          on:click={onCancel}
          disabled={isDeleting}
          class="btn-cancel"
        >
          Cancel
        </button>
        <button
          type="button"
          on:click={onConfirm}
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
    background: white;
    border-radius: 0.5rem;
    padding: 1.5rem;
    max-width: 28rem;
    width: 100%;
    margin: 0 1rem;
  }

  .modal-title {
    font-size: 1.125rem;
    font-weight: 600;
    color: #dc2626;
    margin: 0 0 0.5rem 0;
  }

  .modal-message {
    color: #4b5563;
    margin: 0 0 1rem 0;
    line-height: 1.5;
  }

  .warning-box {
    background: #fef3c7;
    border: 1px solid #fcd34d;
    border-radius: 0.5rem;
    padding: 0.75rem;
    margin-bottom: 1rem;
  }

  .warning-title {
    font-size: 0.875rem;
    font-weight: 500;
    color: #92400e;
    margin: 0 0 0.5rem 0;
  }

  .warning-list {
    font-size: 0.875rem;
    color: #78350f;
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
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .btn-cancel:hover:not(:disabled) {
    background: #f9fafb;
  }

  .btn-cancel:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-confirm {
    background: #dc2626;
    color: white;
    border: none;
  }

  .btn-confirm:hover:not(:disabled) {
    background: #b91c1c;
  }

  .btn-confirm:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
