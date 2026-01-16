<script lang="ts">
  import '../app.css';
  import { QueryClientProvider } from '@tanstack/svelte-query';
  import { queryClient } from '$lib/api/query-client';
  import { authStore } from '$lib/stores/auth.svelte';
  import { onMount } from 'svelte';
  import { browser } from '$app/environment';
  import type { Snippet } from 'svelte';
  import ToastContainer from '$lib/components/ui/ToastContainer.svelte';

  interface Props {
    children: Snippet;
  }

  let { children }: Props = $props();

  // Initialize auth state on mount (client-side only)
  onMount(() => {
    if (browser) {
      authStore.initialize().catch((error) => {
        console.error('Auth initialization failed:', error);
      });
    }
  });

  // Global error handler
  let errorMessage = $state<string | null>(null);

  function handleError(event: ErrorEvent) {
    console.error('Global error:', event.error);
    errorMessage = event.error?.message || 'An unexpected error occurred';

    // Auto-dismiss error after 5 seconds
    setTimeout(() => {
      errorMessage = null;
    }, 5000);
  }

  onMount(() => {
    window.addEventListener('error', handleError);
    return () => {
      window.removeEventListener('error', handleError);
    };
  });
</script>

<QueryClientProvider client={queryClient}>
  <ToastContainer />

  {#if errorMessage}
    <div class="fixed right-4 top-4 z-50 rounded-lg bg-red-500 p-4 text-white shadow-lg">
      <div class="flex items-start gap-2">
        <svg
          class="h-5 w-5 flex-shrink-0"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <p class="flex-1">{errorMessage}</p>
        <button
          onclick={() => {
            errorMessage = null;
          }}
          class="flex-shrink-0"
          aria-label="Dismiss error"
        >
          <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>
    </div>
  {/if}

  {@render children()}
</QueryClientProvider>
