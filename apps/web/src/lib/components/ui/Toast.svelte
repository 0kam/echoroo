<script lang="ts">
  import { fly } from 'svelte/transition';
  import { onMount } from 'svelte';

  export let message: string;
  export let type: 'success' | 'error' | 'warning' | 'info' = 'info';
  export let duration: number = 5000;
  export let onClose: () => void;

  const icons = {
    success: '✓',
    error: '✕',
    warning: '⚠',
    info: 'ℹ',
  };

  const colors = {
    success: 'bg-green-100 border-green-500 text-green-800',
    error: 'bg-red-100 border-red-500 text-red-800',
    warning: 'bg-amber-100 border-amber-500 text-amber-800',
    info: 'bg-blue-100 border-blue-500 text-blue-800',
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
  <button type="button" on:click={onClose} class="toast-close" aria-label="Close">
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

  .bg-green-100 {
    background-color: #d1fae5;
  }

  .border-green-500 {
    border-color: #10b981;
  }

  .text-green-800 {
    color: #065f46;
  }

  .bg-red-100 {
    background-color: #fee2e2;
  }

  .border-red-500 {
    border-color: #ef4444;
  }

  .text-red-800 {
    color: #991b1b;
  }

  .bg-amber-100 {
    background-color: #fef3c7;
  }

  .border-amber-500 {
    border-color: #f59e0b;
  }

  .text-amber-800 {
    color: #92400e;
  }

  .bg-blue-100 {
    background-color: #dbeafe;
  }

  .border-blue-500 {
    border-color: #3b82f6;
  }

  .text-blue-800 {
    color: #1e40af;
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
