<script lang="ts">
  /**
   * ReviewActions - Agree/Disagree/Unsure voting buttons with vote counts.
   *
   * Primary mode: team voting with three vote options (Agree, Disagree, Unsure).
   * - Shows vote counts next to each button
   * - Highlights the current user's vote
   * - Clicking the active vote again removes it (toggle behavior)
   * - Keyboard shortcuts: A = Agree, D = Disagree, U = Unsure (handled by parent grid)
   *
   * Legacy mode: when onConfirm/onReject are provided instead of onVote,
   * the component renders the original Confirm/Reject buttons for backward
   * compatibility with search result review flows that do not use team voting.
   */

  import * as m from '$lib/paraglide/messages';
  import type { VoteValue, VoteSummary } from '$lib/types/detection';

  interface Props {
    /** Current vote summary (null when not yet loaded) — voting mode */
    voteSummary?: VoteSummary | null;
    isLoading?: boolean;
    /** Voting mode: called when user casts a vote */
    onVote?: (vote: VoteValue) => void;
    /** Voting mode: called when user clicks their current active vote to toggle it off */
    onRemoveVote?: () => void;
    /** Legacy mode: confirm detection (original confirm/reject pattern) */
    onConfirm?: () => void;
    /** Legacy mode: reject detection (original confirm/reject pattern) */
    onReject?: () => void;
    /** Legacy mode: current review status for button highlighting */
    legacyStatus?: 'unreviewed' | 'confirmed' | 'rejected';
  }

  let {
    voteSummary = null,
    isLoading = false,
    onVote,
    onRemoveVote,
    onConfirm,
    onReject,
    legacyStatus = 'unreviewed',
  }: Props = $props();

  // Use legacy mode when onConfirm/onReject are provided (no voting)
  const isLegacyMode = $derived(!onVote && (!!onConfirm || !!onReject));

  const myVote = $derived(voteSummary?.my_vote ?? null);
  const agreeCount = $derived(voteSummary?.agree_count ?? 0);
  const disagreeCount = $derived(voteSummary?.disagree_count ?? 0);
  const unsureCount = $derived(voteSummary?.unsure_count ?? 0);

  function handleVoteClick(vote: VoteValue) {
    if (isLoading) return;
    // Toggle off if clicking the same vote
    if (myVote === vote) {
      onRemoveVote?.();
    } else {
      onVote?.(vote);
    }
  }
</script>

{#if isLegacyMode}
  <!-- Legacy confirm/reject mode for backward compatibility (e.g. search result review) -->
  <div class="flex items-center gap-2">
    <button
      type="button"
      data-action="confirm"
      class="inline-flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50
        {legacyStatus === 'confirmed'
          ? 'bg-green-600 text-white hover:bg-green-700'
          : 'border border-green-300 bg-green-50 text-green-700 hover:bg-green-100'}"
      onclick={onConfirm}
      disabled={isLoading}
      title={m.detection_confirm_title()}
      aria-label={m.detection_confirm_aria()}
    >
      {#if isLoading && legacyStatus !== 'rejected'}
        <svg class="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      {:else}
        <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
        </svg>
      {/if}
      {m.detection_confirm_button()}
    </button>

    <button
      type="button"
      data-action="reject"
      class="inline-flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50
        {legacyStatus === 'rejected'
          ? 'bg-red-600 text-white hover:bg-red-700'
          : 'border border-red-300 bg-red-50 text-red-700 hover:bg-red-100'}"
      onclick={onReject}
      disabled={isLoading}
      title={m.detection_reject_title()}
      aria-label={m.detection_reject_aria()}
    >
      {#if isLoading && legacyStatus === 'rejected'}
        <svg class="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      {:else}
        <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
        </svg>
      {/if}
      {m.detection_reject_button()}
    </button>
  </div>
{:else}
  <!-- Voting mode: Agree / Disagree / Unsure -->
  <div class="flex items-center gap-1.5">
    <!-- Agree button -->
    <button
      type="button"
      data-action="agree"
      class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50
        {myVote === 'agree'
          ? 'bg-green-600 text-white hover:bg-green-700'
          : 'border border-green-300 bg-green-50 text-green-700 hover:bg-green-100'}"
      onclick={() => handleVoteClick('agree')}
      disabled={isLoading}
      title={m.vote_agree_title()}
      aria-label={m.vote_agree_aria()}
      aria-pressed={myVote === 'agree'}
    >
      {#if isLoading && myVote === 'agree'}
        <svg class="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      {:else}
        <!-- Thumbs up icon -->
        <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path d="M2 10.5a1.5 1.5 0 113 0v6a1.5 1.5 0 01-3 0v-6zM6 10.333v5.43a2 2 0 001.106 1.79l.05.025A4 4 0 008.943 18h5.416a2 2 0 001.962-1.608l1.2-6A2 2 0 0015.56 8H12V4a2 2 0 00-2-2 1 1 0 00-1 1v.667a4 4 0 01-.8 2.4L6.8 7.933a4 4 0 00-.8 2.4z" />
        </svg>
      {/if}
      <span>{agreeCount > 0 ? agreeCount : m.vote_agree_button()}</span>
    </button>

    <!-- Disagree button -->
    <button
      type="button"
      data-action="disagree"
      class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50
        {myVote === 'disagree'
          ? 'bg-red-600 text-white hover:bg-red-700'
          : 'border border-red-300 bg-red-50 text-red-700 hover:bg-red-100'}"
      onclick={() => handleVoteClick('disagree')}
      disabled={isLoading}
      title={m.vote_disagree_title()}
      aria-label={m.vote_disagree_aria()}
      aria-pressed={myVote === 'disagree'}
    >
      {#if isLoading && myVote === 'disagree'}
        <svg class="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      {:else}
        <!-- Thumbs down icon -->
        <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path d="M18 9.5a1.5 1.5 0 11-3 0v-6a1.5 1.5 0 013 0v6zM14 9.667v-5.43a2 2 0 00-1.105-1.79l-.05-.025A4 4 0 0011.055 2H5.64a2 2 0 00-1.962 1.608l-1.2 6A2 2 0 004.44 12H8v4a2 2 0 002 2 1 1 0 001-1v-.667a4 4 0 01.8-2.4l1.4-1.866a4 4 0 00.8-2.4z" />
        </svg>
      {/if}
      <span>{disagreeCount > 0 ? disagreeCount : m.vote_disagree_button()}</span>
    </button>

    <!-- Unsure button -->
    <button
      type="button"
      data-action="unsure"
      class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-yellow-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50
        {myVote === 'unsure'
          ? 'bg-yellow-500 text-white hover:bg-yellow-600'
          : 'border border-yellow-300 bg-yellow-50 text-yellow-700 hover:bg-yellow-100'}"
      onclick={() => handleVoteClick('unsure')}
      disabled={isLoading}
      title={m.vote_unsure_title()}
      aria-label={m.vote_unsure_aria()}
      aria-pressed={myVote === 'unsure'}
    >
      {#if isLoading && myVote === 'unsure'}
        <svg class="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      {:else}
        <!-- Question mark icon -->
        <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-3a1 1 0 00-.867.5 1 1 0 11-1.731-1A3 3 0 0113 8a3.001 3.001 0 01-2 2.83V11a1 1 0 11-2 0v-1a1 1 0 011-1 1 1 0 100-2zm0 8a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
        </svg>
      {/if}
      <span>{unsureCount > 0 ? unsureCount : m.vote_unsure_button()}</span>
    </button>
  </div>
{/if}
