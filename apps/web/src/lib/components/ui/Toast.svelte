<script lang="ts">
  import { fly } from 'svelte/transition';
  import { onMount } from 'svelte';

  let {
    message,
    type = 'info' as 'success' | 'error' | 'warning' | 'info',
    duration = 5000,
    onClose,
  }: {
    message: string;
    type?: 'success' | 'error' | 'warning' | 'info';
    duration?: number;
    onClose: () => void;
  } = $props();

  const icons = {
    success: '✓',
    error: '✕',
    warning: '⚠',
    info: 'ℹ',
  };

  const colors = {
    success: 'bg-success-light border-success text-success',
    error: 'bg-danger-light border-danger text-danger',
    warning: 'bg-warning-light border-warning text-warning',
    info: 'bg-info-light border-info text-info',
  };

  onMount(() => {
    if (duration > 0) {
      const timeout = setTimeout(onClose, duration);
      return () => clearTimeout(timeout);
    }
  });
</script>

<div
  transition:fly={{ y: -20, duration: 200 }}
  class="toast {colors[type]}"
  role="alert"
>
  <span class="toast-icon">{icons[type]}</span>
  <p class="toast-message">{message}</p>
  <button type="button" onclick={onClose} class="toast-close" aria-label="Close">
    ✕
  </button>
</div>

<style>
  .toast {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    border-left-width: 4px;
    border-radius: 0 0.375rem 0.375rem 0;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    min-width: 320px;
    max-width: 500px;
  }

  .toast-icon {
    font-size: 1.125rem;
    font-weight: bold;
    flex-shrink: 0;
  }

  .toast-message {
    flex: 1;
    margin: 0;
    font-size: 0.875rem;
    line-height: 1.5;
  }

  .toast-close {
    background: none;
    border: none;
    cursor: pointer;
    padding: 0;
    width: 1.5rem;
    height: 1.5rem;
    display: flex;
    align-items: center;
    justify-content: center;
    color: currentColor;
    opacity: 0.6;
    transition: opacity 0.15s ease;
    flex-shrink: 0;
  }

  .toast-close:hover {
    opacity: 1;
  }
</style>
