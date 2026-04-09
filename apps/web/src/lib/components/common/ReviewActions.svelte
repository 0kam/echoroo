<script lang="ts">
  /**
   * ReviewActions - Agree/Disagree/Unsure voting buttons with vote counts.
   *
   * The Agree button opens a compact signal-quality popover so the reviewer
   * can classify how clearly the species is audible:
   *   - Solo     (1): only this species is present
   *   - Dominant (2): this species is dominant, others may be present
   *   - Mixed    (3): this species is present but not dominant
   *
   * Keyboard shortcuts (handled by the parent grid unless in popover):
   *   1 = agree as Solo
   *   2 = agree as Dominant
   *   3 = agree as Mixed
   *   D = Disagree
   *   U = Unsure
   */

  import * as m from '$lib/paraglide/messages';
  import type { VoteValue, VoteSummary, SignalQuality } from '$lib/types/detection';

  interface Props {
    /** Current vote summary (null when not yet loaded) */
    voteSummary?: VoteSummary | null;
    isLoading?: boolean;
    /** Called when user casts an agree vote with a signal quality selection */
    onAgree?: (signalQuality: SignalQuality) => void;
    /** Called when user casts a non-agree vote */
    onVote?: (vote: VoteValue) => void;
    /** Called when user clicks their current active vote to toggle it off */
    onRemoveVote?: () => void;
    /**
     * When true, buttons show icon + count only (no text label).
     * Use on narrow cards to prevent text overflow.
     */
    compact?: boolean;
  }

  let {
    voteSummary = null,
    isLoading = false,
    onAgree,
    onVote,
    onRemoveVote,
    compact = false,
  }: Props = $props();

  const myVote = $derived(voteSummary?.user_vote ?? null);
  const mySignalQuality = $derived(voteSummary?.user_signal_quality ?? null);
  const agreeCount = $derived(voteSummary?.agree_count ?? 0);
  const disagreeCount = $derived(voteSummary?.disagree_count ?? 0);
  const unsureCount = $derived(voteSummary?.unsure_count ?? 0);
  const signalQualityCounts = $derived(
    voteSummary?.signal_quality_counts ?? { solo: 0, dominant: 0, mixed: 0 }
  );

  /** Whether the signal-quality popover is visible */
  let popoverOpen = $state(false);

  /** Container element used for outside-click detection */
  let containerEl: HTMLDivElement | undefined = $state(undefined);

  const QUALITY_OPTIONS: { value: SignalQuality; labelKey: string; descKey: string; color: string }[] = [
    {
      value: 'solo',
      labelKey: 'signal_quality_solo',
      descKey: 'signal_quality_solo_desc',
      color: 'green',
    },
    {
      value: 'dominant',
      labelKey: 'signal_quality_dominant',
      descKey: 'signal_quality_dominant_desc',
      color: 'yellow',
    },
    {
      value: 'mixed',
      labelKey: 'signal_quality_mixed',
      descKey: 'signal_quality_mixed_desc',
      color: 'orange',
    },
  ];

  function openPopover() {
    popoverOpen = true;
  }

  function closePopover() {
    popoverOpen = false;
  }

  function handleAgreeButtonClick() {
    if (isLoading) return;
    if (myVote === 'agree') {
      // Toggle off existing agree vote
      onRemoveVote?.();
      return;
    }
    openPopover();
  }

  function handleQualitySelect(quality: SignalQuality) {
    if (isLoading) return;
    closePopover();
    onAgree?.(quality);
  }

  function handleVoteClick(vote: VoteValue) {
    if (isLoading) return;
    closePopover();
    if (myVote === vote) {
      onRemoveVote?.();
    } else {
      onVote?.(vote);
    }
  }

  /** Build the label shown inside the active Agree button */
  function agreeButtonLabel(): string {
    if (compact) {
      // In compact mode, show count only (or nothing when zero)
      return agreeCount > 0 ? String(agreeCount) : '';
    }
    if (agreeCount === 0) return m.vote_agree_button();
    if (agreeCount > 0) {
      const { solo, dominant, mixed } = signalQualityCounts;
      // If all agree votes have no quality data, just show the count
      if (solo === 0 && dominant === 0 && mixed === 0) return String(agreeCount);
      // Build a compact breakdown string
      const parts: string[] = [];
      if (solo > 0) parts.push(`${solo}${m.signal_quality_solo_abbr()}`);
      if (dominant > 0) parts.push(`${dominant}${m.signal_quality_dominant_abbr()}`);
      if (mixed > 0) parts.push(`${mixed}${m.signal_quality_mixed_abbr()}`);
      return parts.join(' ');
    }
    return m.vote_agree_button();
  }

  /** Color class for a quality option button */
  function qualityButtonClass(color: string, selected: boolean): string {
    const base = 'flex items-start gap-2 rounded px-2 py-1.5 text-xs text-left transition-colors w-full';
    if (color === 'green') {
      return `${base} ${selected ? 'bg-success text-white' : 'bg-success-light text-success hover:bg-success/20 border border-success/30'}`;
    }
    if (color === 'yellow') {
      return `${base} ${selected ? 'bg-warning text-white' : 'bg-warning-light text-warning hover:bg-warning/20 border border-warning/30'}`;
    }
    // orange
    return `${base} ${selected ? 'bg-primary-600 text-white' : 'bg-primary-50 text-primary-700 hover:bg-primary-100 border border-primary-200 dark:bg-primary-900/20 dark:text-primary-400 dark:border-primary-700 dark:hover:bg-primary-900/40'}`;
  }

  /** Outside-click handler to close the popover */
  function handleWindowClick(event: MouseEvent) {
    if (!popoverOpen) return;
    if (containerEl && !containerEl.contains(event.target as Node)) {
      closePopover();
    }
  }
</script>

<svelte:window onclick={handleWindowClick} />

<!-- Voting mode: Agree (with quality popover) / Disagree / Unsure -->
<div class="relative flex flex-nowrap items-center gap-1" bind:this={containerEl}>
  <!-- Agree button + popover wrapper -->
  <div class="relative">
    <!-- Agree button -->
    <button
      type="button"
      data-action="agree"
      class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-success focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50
        {myVote === 'agree'
          ? 'bg-success text-white hover:bg-success/90'
          : 'border border-success/40 bg-success-light text-success hover:bg-success/20'}"
      onclick={handleAgreeButtonClick}
      disabled={isLoading}
      title={myVote === 'agree' ? m.vote_agree_title_active() : m.vote_agree_title()}
      aria-label={m.vote_agree_aria()}
      aria-pressed={myVote === 'agree'}
      aria-haspopup="listbox"
      aria-expanded={popoverOpen}
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
      {#if agreeButtonLabel()}
        <span>{agreeButtonLabel()}</span>
      {/if}
      <!-- Chevron indicator when not yet agreed -->
      {#if myVote !== 'agree'}
        <svg class="h-2.5 w-2.5 opacity-60" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
        </svg>
      {/if}
    </button>

    <!-- Signal quality popover -->
    {#if popoverOpen}
      <div
        class="absolute bottom-full left-0 z-50 mb-1 w-48 rounded-lg border border-stone-200 bg-surface-card shadow-lg"
        role="listbox"
        aria-label={m.signal_quality_popover_label()}
      >
        <!-- Popover header -->
        <div class="border-b border-stone-100 px-2 py-1.5">
          <p class="text-xs font-semibold text-stone-600">{m.signal_quality_popover_title()}</p>
        </div>

        <!-- Quality options -->
        <div class="flex flex-col gap-1 p-1.5">
          {#each QUALITY_OPTIONS as option, i (option.value)}
            <button
              type="button"
              role="option"
              aria-selected={mySignalQuality === option.value}
              class={qualityButtonClass(option.color, mySignalQuality === option.value)}
              onclick={() => handleQualitySelect(option.value)}
            >
              <!-- Keyboard shortcut badge -->
              <span
                class="mt-0.5 shrink-0 rounded border border-current/30 bg-current/10 px-1 font-mono text-[10px] leading-tight"
              >
                {i + 1}
              </span>
              <span class="flex flex-col">
                <span class="font-semibold leading-tight">
                  <!-- Use dynamic message lookup via if/else to stay compatible with Paraglide -->
                  {#if option.value === 'solo'}
                    {m.signal_quality_solo()}
                  {:else if option.value === 'dominant'}
                    {m.signal_quality_dominant()}
                  {:else}
                    {m.signal_quality_mixed()}
                  {/if}
                </span>
                <span class="mt-0.5 text-[10px] leading-snug opacity-75">
                  {#if option.value === 'solo'}
                    {m.signal_quality_solo_desc()}
                  {:else if option.value === 'dominant'}
                    {m.signal_quality_dominant_desc()}
                  {:else}
                    {m.signal_quality_mixed_desc()}
                  {/if}
                </span>
              </span>
            </button>
          {/each}
        </div>
      </div>
    {/if}
  </div>

  <!-- Disagree button -->
  <button
    type="button"
    data-action="disagree"
    class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-danger focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50
      {myVote === 'disagree'
        ? 'bg-danger text-white hover:bg-danger/90'
        : 'border border-danger/40 bg-danger-light text-danger hover:bg-danger/20'}"
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
    {#if !compact || disagreeCount > 0}
      <span>{disagreeCount > 0 ? disagreeCount : m.vote_disagree_button()}</span>
    {/if}
  </button>

  <!-- Unsure button -->
  <button
    type="button"
    data-action="unsure"
    class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-warning focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50
      {myVote === 'unsure'
        ? 'bg-warning text-white hover:bg-warning/90'
        : 'border border-warning/40 bg-warning-light text-warning hover:bg-warning/20'}"
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
    {#if !compact || unsureCount > 0}
      <span>{unsureCount > 0 ? unsureCount : m.vote_unsure_button()}</span>
    {/if}
  </button>
</div>
