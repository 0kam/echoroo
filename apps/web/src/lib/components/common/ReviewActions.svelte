<script lang="ts">
  /**
   * ReviewActions - Confirm/Reject buttons with current status badge.
   *
   * Provides the review action controls for a detection or search result card.
   * Works for both DetectionStatus and SearchResultStatus since both use the
   * same union: 'unreviewed' | 'confirmed' | 'rejected'.
   */

  import * as m from '$lib/paraglide/messages';

  type ReviewStatus = 'unreviewed' | 'confirmed' | 'rejected';

  interface Props {
    status: ReviewStatus;
    isLoading?: boolean;
    onConfirm: () => void;
    onReject: () => void;
  }

  let { status, isLoading = false, onConfirm, onReject }: Props = $props();

  const statusLabel = $derived(getStatusLabel(status));
  const statusClass = $derived(getStatusClass(status));

  function getStatusLabel(s: ReviewStatus): string {
    switch (s) {
      case 'confirmed':
        return m.detection_status_confirmed();
      case 'rejected':
        return m.detection_status_rejected();
      default:
        return m.detection_status_unreviewed();
    }
  }

  function getStatusClass(s: ReviewStatus): string {
    switch (s) {
      case 'confirmed':
        return 'bg-green-100 text-green-800 border-green-200';
      case 'rejected':
        return 'bg-red-100 text-red-800 border-red-200';
      default:
        return 'bg-stone-100 text-stone-600 border-stone-200';
    }
  }
</script>

<div class="flex items-center gap-2">
  <!-- Current status badge -->
  <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium {statusClass}">
    {statusLabel}
  </span>

  <!-- Confirm button -->
  <button
    type="button"
    class="inline-flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50
      {status === 'confirmed'
        ? 'bg-green-600 text-white hover:bg-green-700'
        : 'border border-green-300 bg-green-50 text-green-700 hover:bg-green-100'}"
    onclick={onConfirm}
    disabled={isLoading}
    title={m.detection_confirm_title()}
    aria-label={m.detection_confirm_aria()}
  >
    {#if isLoading && status !== 'rejected'}
      <svg class="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    {:else}
      <!-- Checkmark icon -->
      <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
      </svg>
    {/if}
    {m.detection_confirm_button()}
  </button>

  <!-- Reject button -->
  <button
    type="button"
    class="inline-flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50
      {status === 'rejected'
        ? 'bg-red-600 text-white hover:bg-red-700'
        : 'border border-red-300 bg-red-50 text-red-700 hover:bg-red-100'}"
    onclick={onReject}
    disabled={isLoading}
    title={m.detection_reject_title()}
    aria-label={m.detection_reject_aria()}
  >
    {#if isLoading && status === 'rejected'}
      <svg class="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    {:else}
      <!-- X icon -->
      <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
      </svg>
    {/if}
    {m.detection_reject_button()}
  </button>
</div>
