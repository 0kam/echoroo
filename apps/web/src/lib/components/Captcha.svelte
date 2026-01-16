<script lang="ts">
  /**
   * Cloudflare Turnstile CAPTCHA component
   */

  import { onMount } from 'svelte';

  interface Props {
    siteKey: string;
    onVerify: (token: string) => void;
    onError?: (error: string) => void;
    onExpire?: () => void;
  }

  let { siteKey, onVerify, onError, onExpire }: Props = $props();

  let container: HTMLDivElement | undefined = $state(undefined);
  let widgetId: string | null = $state(null);
  let isLoading = $state(true);
  let error = $state<string | null>(null);

  /**
   * Load Turnstile script
   */
  function loadTurnstileScript(): Promise<void> {
    return new Promise((resolve, reject) => {
      // Check if script already loaded
      if (window.turnstile) {
        resolve();
        return;
      }

      const script = document.createElement('script');
      script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
      script.async = true;
      script.defer = true;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error('Failed to load Turnstile script'));
      document.head.appendChild(script);
    });
  }

  /**
   * Render Turnstile widget
   */
  function renderWidget() {
    if (!container || !window.turnstile) return;

    try {
      widgetId = window.turnstile.render(container, {
        sitekey: siteKey,
        callback: (token: string) => {
          error = null;
          onVerify(token);
        },
        'error-callback': (err: string) => {
          error = 'CAPTCHA verification failed';
          if (onError) {
            onError(err);
          }
        },
        'expired-callback': () => {
          error = 'CAPTCHA expired, please try again';
          if (onExpire) {
            onExpire();
          }
        },
        theme: 'light',
        size: 'normal',
      });

      isLoading = false;
    } catch (err) {
      error = 'Failed to initialize CAPTCHA';
      isLoading = false;
      console.error('Turnstile render error:', err);
    }
  }

  /**
   * Reset widget
   */
  export function reset() {
    if (widgetId && window.turnstile) {
      window.turnstile.reset(widgetId);
      error = null;
    }
  }

  onMount(() => {
    loadTurnstileScript()
      .then(() => {
        renderWidget();
      })
      .catch((err) => {
        error = 'Failed to load CAPTCHA';
        isLoading = false;
        console.error('Turnstile load error:', err);
      });

    return () => {
      if (widgetId && window.turnstile) {
        window.turnstile.remove(widgetId);
      }
    };
  });
</script>

<div class="captcha-container">
  {#if isLoading}
    <div class="flex items-center justify-center py-4">
      <div class="h-8 w-8 animate-spin rounded-full border-4 border-gray-300 border-t-blue-600"></div>
      <span class="ml-2 text-sm text-gray-600">Loading CAPTCHA...</span>
    </div>
  {/if}

  <div bind:this={container} class:hidden={isLoading}></div>

  {#if error}
    <div class="mt-2 text-sm text-red-600" role="alert">
      {error}
    </div>
  {/if}
</div>

<style>
  .captcha-container {
    min-height: 65px;
  }
</style>
