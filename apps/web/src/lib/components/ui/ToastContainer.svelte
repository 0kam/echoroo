<script lang="ts">
  import { toasts } from '$lib/stores/toast';
  import Toast from './Toast.svelte';
</script>

<div class="toast-container">
  {#each $toasts as toast (toast.id)}
    <Toast
      message={toast.message}
      type={toast.type}
      duration={toast.duration}
      onClose={() => toasts.remove(toast.id)}
    />
  {/each}
</div>

<style>
  .toast-container {
    position: fixed;
    top: 1rem;
    right: 1rem;
    z-index: 9999;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    pointer-events: none;
  }

  .toast-container :global(.toast) {
    pointer-events: auto;
  }
</style>
