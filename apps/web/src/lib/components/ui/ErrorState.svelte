<script lang="ts">
  /**
   * ErrorState — reusable inline error card.
   *
   * Generalises the bordered danger card pattern first used in
   * `DetectionReviewGrid.svelte`: an alert icon, a primary message, an
   * optional secondary detail line (derived from an `error`), and an
   * optional retry button. Uses the Rosé Pine `danger` / Love semantic
   * classes so it matches the rest of the app.
   */
  import { ApiError } from '$lib/api/client';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    /** Primary, human-readable message. Defaults to a generic load error. */
    message?: string;
    /**
     * The underlying error, if any. Its message / `ApiError` detail is
     * rendered as a secondary line below the primary message.
     */
    error?: unknown;
    /** When provided, renders a retry button that invokes this callback. */
    onRetry?: () => void;
  }

  let { message, error, onRetry }: Props = $props();

  const primaryMessage = $derived(message ?? m.error_load_generic());

  /** Extract a secondary detail string from the supplied error, if any. */
  const detail = $derived.by(() => {
    if (!error) return null;
    if (error instanceof ApiError) {
      return error.detail ?? error.message ?? null;
    }
    if (error instanceof Error) {
      return error.message || null;
    }
    return null;
  });
</script>

<div class="rounded-lg border border-danger/30 bg-danger-light px-4 py-6 text-center">
  <svg
    class="mx-auto mb-2 h-8 w-8 text-danger"
    fill="none"
    viewBox="0 0 24 24"
    stroke="currentColor"
    aria-hidden="true"
  >
    <path
      stroke-linecap="round"
      stroke-linejoin="round"
      stroke-width="2"
      d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
    />
  </svg>
  <p class="text-sm font-medium text-danger">{primaryMessage}</p>
  {#if detail}
    <p class="mt-1 text-xs text-danger/80">{detail}</p>
  {/if}
  {#if onRetry}
    <button
      type="button"
      onclick={onRetry}
      class="mt-3 rounded-md border border-danger/30 bg-danger-light px-3 py-1.5 text-xs font-medium text-danger hover:bg-danger/20"
    >
      {m.error_retry()}
    </button>
  {/if}
</div>
