<script lang="ts">
  export let isOpen: boolean = false;
  export let title: string;
  export let message: string;
  export let confirmText: string = 'Confirm';
  export let cancelText: string = 'Cancel';
  export let confirmButtonClass: string = 'btn-danger';
  export let onConfirm: () => void | Promise<void>;
  export let onCancel: () => void = () => {};
  export let warningItems: string[] = [];

  let isProcessing = false;

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

{#if isOpen}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    class="dialog-backdrop"
    on:click={handleBackdropClick}
    on:keydown={handleKeydown}
    role="dialog"
    aria-modal="true"
    aria-labelledby="dialog-title"
  >
    <div class="dialog-content">
      <div class="dialog-header">
        <h2 id="dialog-title">{title}</h2>
      </div>

      <div class="dialog-body">
        <p class="dialog-message">{message}</p>

        {#if warningItems.length > 0}
          <div class="warning-box">
            <div class="warning-header">
              <svg class="warning-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path
                  d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
                  stroke-width="2"
                />
                <line x1="12" y1="9" x2="12" y2="13" stroke-width="2" />
                <line x1="12" y1="17" x2="12.01" y2="17" stroke-width="2" />
              </svg>
              <span class="warning-title">The following will be deleted:</span>
            </div>
            <ul class="warning-list">
              {#each warningItems as item}
                <li>{item}</li>
              {/each}
            </ul>
          </div>
        {/if}
      </div>

      <div class="dialog-footer">
        <button
          type="button"
          class="btn btn-secondary"
          on:click={handleCancel}
          disabled={isProcessing}
        >
          {cancelText}
        </button>
        <button
          type="button"
          class="btn {confirmButtonClass}"
          on:click={handleConfirm}
          disabled={isProcessing}
        >
          {#if isProcessing}
            Processing...
          {:else}
            {confirmText}
          {/if}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .dialog-backdrop {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: 1rem;
  }

  .dialog-content {
    background: white;
    border-radius: 0.5rem;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
    max-width: 500px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
  }

  .dialog-header {
    padding: 1.5rem 1.5rem 1rem 1.5rem;
    border-bottom: 1px solid #e5e7eb;
  }

  .dialog-header h2 {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 600;
    color: #111827;
  }

  .dialog-body {
    padding: 1.5rem;
  }

  .dialog-message {
    margin: 0 0 1rem 0;
    color: #374151;
    line-height: 1.5;
  }

  .warning-box {
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 0.375rem;
    padding: 1rem;
  }

  .warning-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }

  .warning-icon {
    width: 20px;
    height: 20px;
    color: #dc2626;
    flex-shrink: 0;
  }

  .warning-title {
    font-weight: 500;
    color: #991b1b;
    font-size: 0.875rem;
  }

  .warning-list {
    margin: 0;
    padding-left: 1.5rem;
    color: #7f1d1d;
    font-size: 0.875rem;
  }

  .warning-list li {
    margin-bottom: 0.25rem;
  }

  .dialog-footer {
    padding: 1rem 1.5rem 1.5rem 1.5rem;
    border-top: 1px solid #e5e7eb;
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
  }

  .btn {
    padding: 0.625rem 1.25rem;
    font-size: 0.875rem;
    font-weight: 500;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
    border: none;
  }

  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-secondary {
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .btn-secondary:hover:not(:disabled) {
    background: #f9fafb;
  }

  .btn-danger {
    background: #dc2626;
    color: white;
  }

  .btn-danger:hover:not(:disabled) {
    background: #b91c1c;
  }
</style>
