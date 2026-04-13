<script lang="ts">
  /**
   * ReviewCard - Shared spectrogram card with confirm/reject actions.
   *
   * Used by DetectionCard (detection review) and directly in ResultsPanel
   * (similarity search review). Renders a MiniSpectrogram with an audio
   * play button overlay, a score badge, and ReviewActions at the bottom.
   *
   * The optional `extraBody` snippet prop allows callers to inject
   * detection-specific content (e.g. species corrector, source badge)
   * between the time range and the review actions.
   */

  import { onDestroy, type Snippet } from 'svelte';
  import type { DetectionStatus, VoteSummary, VoteValue, SignalQuality } from '$lib/types/detection';
  import * as m from '$lib/paraglide/messages';
  import { createAudioPlayer } from '$lib/utils/audioPlayback.svelte';
  import { getConsensusCardBorderClass } from '$lib/utils/statusFormatters';
  import MiniSpectrogram from './MiniSpectrogram.svelte';
  import ReviewActions from './ReviewActions.svelte';

  interface Props {
    projectId: string;
    recordingId: string;
    recordingName: string;
    startTime: number;
    endTime: number;
    freqLow?: number;
    freqHigh?: number;
    /** Review status — determines border colour and status badge */
    status: DetectionStatus;
    /**
     * Numeric score (0–1) displayed as a percentage badge on the spectrogram.
     * Pass null to hide the badge entirely.
     */
    scoreValue: number | null;
    /** Accessible label for the score badge (e.g. "confidence" or "similarity") */
    scoreLabel?: string;
    /** Tailwind class string controlling badge colour — caller supplies this */
    scoreBadgeClass?: string;
    /** Show loading overlay when a mutation is in flight */
    isLoading?: boolean;
    /** Highlight the card (e.g. keyboard-focused item in a list) */
    isSelected?: boolean;
    /** Vote summary for the voting-based review UI */
    voteSummary?: VoteSummary | null;
    /** Called when user casts an agree vote with a signal quality selection */
    onAgree?: (signalQuality: SignalQuality) => void;
    onVote?: (vote: VoteValue) => void;
    onRemoveVote?: () => void;
    /**
     * When true, vote buttons show icon + count only (no text label).
     * Pass this on narrow-column grids to prevent text overflow.
     */
    compact?: boolean;
    /**
     * When true, the Agree button skips the signal-quality popover and agrees
     * directly without signal_quality. Pass-through to ReviewActions.
     * Default: false.
     */
    simpleMode?: boolean;
    /**
     * Whether this card's audio is currently playing, controlled by a parent
     * navigation hook. When provided, the play button reflects this state
     * instead of the internal player's state.
     */
    externalIsPlaying?: boolean;
    /**
     * Whether the external player is loading audio for this card.
     */
    externalIsLoadingAudio?: boolean;
    /**
     * Callback when the play button is clicked. When provided, delegates
     * playback control to the parent instead of using the internal player.
     */
    onPlayToggle?: () => void;
    /**
     * Optional callback invoked when the user clicks (or activates via keyboard)
     * the spectrogram area. When provided, the spectrogram wrapper becomes a
     * focusable button that calls this handler, enabling click-to-select behaviour
     * in parent list/grid components.
     */
    onClickSelect?: () => void;
    /**
     * Optional snippet injected at the top of the card body,
     * before recording name and time range.
     */
    extraHeader?: Snippet;
    /**
     * Optional snippet injected between the time range and review actions.
     */
    extraBody?: Snippet;
  }

  let {
    projectId,
    recordingId,
    recordingName,
    startTime,
    endTime,
    freqLow,
    freqHigh,
    status,
    scoreValue,
    scoreLabel = '',
    scoreBadgeClass = 'bg-stone-100 text-stone-600',
    isLoading = false,
    isSelected = false,
    voteSummary = null,
    onAgree,
    onVote,
    onRemoveVote,
    compact = false,
    simpleMode = false,
    externalIsPlaying,
    externalIsLoadingAudio,
    onPlayToggle,
    onClickSelect,
    extraHeader,
    extraBody,
  }: Props = $props();

  // Use an internal player only when no external playback control is provided
  const internalPlayer = onPlayToggle ? null : createAudioPlayer(projectId);

  // Effective playback state: prefer external props when available
  const effectiveIsPlaying = $derived(
    onPlayToggle ? (externalIsPlaying ?? false) : (internalPlayer?.isPlaying ?? false)
  );
  const effectiveIsLoadingAudio = $derived(
    onPlayToggle ? (externalIsLoadingAudio ?? false) : (internalPlayer?.isLoadingAudio ?? false)
  );

  const scorePercent = $derived(scoreValue !== null ? Math.round(scoreValue * 100) : null);

  const borderClass = $derived.by(() => {
    if (voteSummary) {
      // Use consensus-based border when consensus is reached
      if (voteSummary.consensus_status !== 'needs_votes') {
        return getConsensusCardBorderClass(voteSummary.consensus_status, isSelected);
      }
      // Fallback to user's own vote for single-voter / needs_votes scenarios
      if (voteSummary.user_vote === 'agree') return 'border-success/60 ring-1 ring-success/30';
      if (voteSummary.user_vote === 'disagree') return 'border-danger/60 ring-1 ring-danger/30';
      if (voteSummary.user_vote === 'unsure') return 'border-warning/60 ring-1 ring-warning/30';
      return isSelected ? 'border-primary-400 ring-1 ring-primary-300' : 'border-stone-200';
    }
    // No voteSummary — use annotation status (used by DetectionCard)
    if (status === 'confirmed') return 'border-success ring-1 ring-success/50';
    if (status === 'rejected') return 'border-danger ring-1 ring-danger/50';
    return isSelected ? 'border-primary-400 ring-1 ring-primary-300' : 'border-stone-200';
  });

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(1);
    return `${mins}:${secs.padStart(4, '0')}`;
  }

  function formatDuration(start: number, end: number): string {
    return `${formatTime(start)} \u2013 ${formatTime(end)}`;
  }

  function handlePlayToggle(event: MouseEvent) {
    // Prevent click from bubbling up to the spectrogram wrapper's onClickSelect handler
    event.stopPropagation();
    if (onPlayToggle) {
      onPlayToggle();
    } else {
      internalPlayer?.toggle(recordingId, startTime, endTime);
    }
  }

  function handleAgree(signalQuality: SignalQuality | undefined) {
    internalPlayer?.stop();
    onAgree?.(signalQuality as SignalQuality);
  }

  function handleVote(vote: VoteValue) {
    internalPlayer?.stop();
    onVote?.(vote);
  }

  function handleRemoveVote() {
    internalPlayer?.stop();
    onRemoveVote?.();
  }

  onDestroy(() => {
    internalPlayer?.cleanup();
  });
</script>

<div
  class="relative flex flex-col overflow-hidden rounded-lg border bg-surface-card shadow-sm transition-all duration-200 ease-in-out hover:shadow-md {borderClass}"
  role="article"
  aria-label="Review card: {recordingName}"
>
  <!-- Loading overlay while a mutation is in flight -->
  {#if isLoading}
    <div class="absolute inset-0 z-10 flex items-center justify-center rounded-lg bg-surface-card/60">
      <svg class="h-5 w-5 animate-spin text-stone-400" viewBox="0 0 24 24" fill="none">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>
  {/if}

  <!-- Spectrogram + overlaid controls -->
  <!-- When onClickSelect is provided, the wrapper becomes a focusable button-like region -->
  <div
    class="relative {onClickSelect ? 'cursor-pointer' : ''}"
    role={onClickSelect ? 'button' : undefined}
    tabindex={onClickSelect ? 0 : undefined}
    onclick={onClickSelect ? () => onClickSelect?.() : undefined}
    onkeydown={onClickSelect
      ? (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            e.stopPropagation();
            onClickSelect?.();
          }
        }
      : undefined}
    aria-label={onClickSelect ? `Select sample: ${recordingName}` : undefined}
  >
    <MiniSpectrogram
      {projectId}
      {recordingId}
      {startTime}
      {endTime}
      {freqLow}
      {freqHigh}
    />

    <!-- Score badge (top-left) — hidden when scoreValue is null -->
    {#if scorePercent !== null}
      <span
        class="absolute left-1 top-1 rounded px-1.5 py-0.5 text-xs font-semibold {scoreBadgeClass}"
        title={scoreLabel}
      >
        {scorePercent}%
      </span>
    {/if}

    <!-- Audio play/stop button (top-right) -->
    <button
      type="button"
      class="absolute right-1 top-1 flex h-7 w-7 items-center justify-center rounded-full bg-black/50 text-white transition-colors hover:bg-black/70 focus:outline-none focus:ring-2 focus:ring-white/50 disabled:cursor-not-allowed disabled:opacity-60"
      onclick={handlePlayToggle}
      disabled={effectiveIsLoadingAudio}
      aria-label={effectiveIsPlaying ? m.detection_stop_audio_aria() : m.detection_play_audio_aria()}
      title={effectiveIsLoadingAudio
        ? m.detection_loading_audio_title()
        : effectiveIsPlaying
          ? m.detection_stop_title()
          : m.detection_play_title()}
    >
      {#if effectiveIsLoadingAudio}
        <div class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white"></div>
      {:else if effectiveIsPlaying}
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
          <rect x="6" y="6" width="12" height="12" rx="1" />
        </svg>
      {:else}
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5 3 19 12 5 21 5 3" />
        </svg>
      {/if}
    </button>
  </div>

  <!-- Card body -->
  <div class="flex flex-col gap-2 p-2.5">
    <!-- Optional header content injected before recording name -->
    {#if extraHeader}
      {@render extraHeader()}
    {/if}

    <!-- Recording name -->
    <span class="truncate text-xs text-stone-500" title={recordingName}>
      {recordingName}
    </span>
    <!-- Time range -->
    <span class="font-mono text-xs text-stone-400">
      {formatDuration(startTime, endTime)}
    </span>

    <!-- Optional caller-specific content (species corrector, source badge, etc.) -->
    {#if extraBody}
      {@render extraBody()}
    {/if}

    <!-- Review actions: Agree / Disagree / Unsure voting buttons -->
    <ReviewActions
      {voteSummary}
      {isLoading}
      {compact}
      {simpleMode}
      onAgree={handleAgree}
      onVote={handleVote}
      onRemoveVote={handleRemoveVote}
    />
  </div>
</div>
