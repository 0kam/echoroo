<script lang="ts">
  /**
   * DetectionCard - Compact card showing a single detection with voting review actions.
   *
   * Wraps ReviewCard (shared component) and adds detection-specific features:
   * species name/confidence header, source badge, vote summary display,
   * and SpeciesCorrector for reassigning the species tag.
   */

  import type { Detection, VoteSummary, VoteValue, SignalQuality } from '$lib/types/detection';
  import * as m from '$lib/paraglide/messages';
  import { getLocale } from '$lib/paraglide/runtime';
  import { getConsensusStatusBadgeClass, getConsensusStatusLabel } from '$lib/utils/statusFormatters';
  import { displayCommonName } from '$lib/utils/speciesFormatters';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import ReviewCard from '$lib/components/common/ReviewCard.svelte';
  import SpeciesCorrector from './SpeciesCorrector.svelte';
  import VoteSourceBreakdown from './VoteSourceBreakdown.svelte';
  import VoterList from './VoterList.svelte';
  import { getDetectionVoteSummary } from '$lib/api/votes';

  interface Props {
    detection: Detection;
    projectId: string;
    isSelected?: boolean;
    isLoading?: boolean;
    /** Vote summary for this detection (loaded by parent or lazy-loaded) */
    voteSummary?: VoteSummary | null;
    /** Whether this card's audio is currently playing (controlled by parent navigation) */
    externalIsPlaying?: boolean;
    /** Whether the external player is loading audio for this card */
    externalIsLoadingAudio?: boolean;
    /** Callback when the play button is clicked (delegates to parent's player) */
    onPlayToggle?: () => void;
    onAgree: (detectionId: string, signalQuality: SignalQuality) => void;
    onVote: (detectionId: string, vote: VoteValue) => void;
    onRemoveVote: (detectionId: string) => void;
    onChangeSpecies: (detectionId: string, newTagId: string) => void;
  }

  let {
    detection,
    projectId,
    isSelected = false,
    isLoading = false,
    voteSummary = null,
    externalIsPlaying,
    externalIsLoadingAudio,
    onPlayToggle,
    onAgree,
    onVote,
    onRemoveVote,
    onChangeSpecies,
  }: Props = $props();

  const confidencePercent = $derived(
    detection.confidence != null ? Math.round(detection.confidence * 100) : null
  );
  const recordingName = $derived(
    detection.recording?.filename ?? detection.recording_id.slice(0, 8) + '...'
  );
  // Resolve the species label in the following priority:
  //   tag.vernacular_name → tag.common_name → tag.name → 'Unidentified'.
  // `displayCommonName` reads the locale-resolved `vernacular_name` that the
  // backend attaches when the `locale` query param is passed.
  const tagName = $derived(displayCommonName(detection.tag) ?? m.detection_species_unidentified());

  const confidenceBadgeClass = $derived(
    confidencePercent == null
      ? 'bg-stone-100 text-stone-600'
      : confidencePercent >= 80
        ? 'bg-success-light text-success'
        : confidencePercent >= 50
          ? 'bg-warning-light text-warning'
          : 'bg-danger-light text-danger'
  );

  // Brief scale animation when a mutation completes (isLoading transitions true -> false)
  let justUpdated = $state(false);
  let prevIsLoading = $state(false);

  $effect(() => {
    if (prevIsLoading && !isLoading) {
      justUpdated = true;
      setTimeout(() => {
        justUpdated = false;
      }, 400);
    }
    prevIsLoading = isLoading;
  });

  function getSourceLabel(source: string): string {
    switch (source) {
      case 'birdnet':
        return 'BirdNET';
      case 'perch_search':
        return 'Perch';
      case 'human':
        return m.detection_source_human();
      default:
        return source;
    }
  }

  function handleAgree(signalQuality: SignalQuality) {
    onAgree(detection.id, signalQuality);
  }

  function handleVote(vote: VoteValue) {
    onVote(detection.id, vote);
  }

  function handleRemoveVote() {
    onRemoveVote(detection.id);
  }

  function handleChangeSpecies(newTagId: string) {
    onChangeSpecies(detection.id, newTagId);
  }

  // ---------------------------------------------------------------------
  // Lazy-loaded full vote summary (FR-038 / FR-039)
  // ---------------------------------------------------------------------
  // The detection list endpoint only includes compact `DetectionVoteCounts`
  // and does NOT carry per-source counts or `voters[]`.  We lazy-load the
  // full summary only when the user expands the voter section so the grid
  // does not fan out N detection-vote requests on mount.
  //
  // Decision: option C (fetch-on-expand) was chosen over option A
  // (mount-time fetch) because most reviewers scroll past most cards
  // without inspecting voters.  Per-source counts shown in the compact
  // breakdown remain `0` until the section is opened — the prop
  // `voteSummary` from the parent grid already drives the row when the
  // parent has the data, and a freshly-loaded summary supersedes it once
  // the query resolves.
  let votersExpanded = $state(false);
  const queryClient = useQueryClient();

  const fullSummaryQuery = $derived(
    createQuery<VoteSummary>({
      queryKey: ['detection-vote-summary', projectId, detection.id],
      queryFn: () => getDetectionVoteSummary(projectId, detection.id),
      enabled: votersExpanded,
      // Keep the cached summary fresh for a minute — re-opening the section
      // within that window reuses the cache instead of re-fetching.
      staleTime: 60_000,
    })
  );

  // Resolved summary: the lazy query takes precedence once it has data,
  // otherwise we fall back to whatever the parent grid passed in.
  const resolvedSummary = $derived<VoteSummary | null>(
    $fullSummaryQuery.data ?? voteSummary ?? null
  );

  // Refetch the full summary after a vote mutation finishes (isLoading
  // transitions from `true` to `false`) so the voter list and per-source
  // counts reflect the new vote without a full grid invalidation cycle.
  let prevIsLoadingForSummary = $state(false);
  $effect(() => {
    if (prevIsLoadingForSummary && !isLoading && votersExpanded) {
      queryClient.invalidateQueries({
        queryKey: ['detection-vote-summary', projectId, detection.id],
      });
    }
    prevIsLoadingForSummary = isLoading;
  });
</script>

<!-- Wrapper applies the scale animation on top of ReviewCard -->
<div
  class="transition-transform duration-300 ease-in-out {justUpdated ? 'scale-[1.02]' : ''}"
  role="article"
  aria-label={m.detection_card_aria_label({ name: tagName })}
>
  <ReviewCard
    {projectId}
    recordingId={detection.recording_id}
    {recordingName}
    startTime={detection.start_time}
    endTime={detection.end_time}
    freqLow={detection.freq_low ?? undefined}
    freqHigh={detection.freq_high ?? undefined}
    status={detection.status}
    scoreValue={null}
    {isLoading}
    {isSelected}
    voteSummary={resolvedSummary}
    {externalIsPlaying}
    {externalIsLoadingAudio}
    {onPlayToggle}
    onAgree={handleAgree}
    onVote={handleVote}
    onRemoveVote={handleRemoveVote}
  >
    {#snippet extraHeader()}
      <!-- Tag name and confidence badge -->
      <div class="flex items-center justify-between gap-2">
        <span class="truncate text-sm font-semibold text-stone-800" title={tagName}>
          {tagName}
        </span>
        {#if confidencePercent !== null}
          <span
            class="shrink-0 rounded px-1.5 py-0.5 text-xs font-medium {confidenceBadgeClass}"
            title={m.detection_model_confidence_tooltip()}
          >
            {confidencePercent}%
          </span>
        {/if}
      </div>
    {/snippet}

    {#snippet extraBody()}
      <!-- Vote summary indicator -->
      {#if resolvedSummary && (resolvedSummary.agree_count + resolvedSummary.disagree_count + resolvedSummary.unsure_count) > 0}
        <div class="flex flex-wrap items-center gap-1.5">
          <!-- Consensus badge -->
          <span
            class="rounded border px-1.5 py-0.5 text-xs font-medium {getConsensusStatusBadgeClass(resolvedSummary.consensus_status)}"
          >
            {getConsensusStatusLabel(resolvedSummary.consensus_status, {
              needs_votes: m.consensus_needs_votes,
              agreed: m.consensus_agreed,
              disputed: m.consensus_disputed,
              rejected: m.consensus_rejected,
            })}
          </span>
          <!-- Vote ratio -->
          <span class="text-xs text-stone-400">
            {m.vote_summary_ratio({ agree: resolvedSummary.agree_count, total: resolvedSummary.agree_count + resolvedSummary.disagree_count + resolvedSummary.unsure_count })}
          </span>
          <!-- Signal quality breakdown (only when there are agree votes with quality data) -->
          <!-- Per-source vote breakdown (FR-038): Member / Non-member / Trusted.
               Counts will be 0 until the voter section is expanded — see the
               lazy-load comment at the top of the script block. -->
          <VoteSourceBreakdown
            memberAgree={resolvedSummary.member_agree}
            memberDisagree={resolvedSummary.member_disagree}
            guestAuthenticatedAgree={resolvedSummary.guest_authenticated_agree}
            guestAuthenticatedDisagree={resolvedSummary.guest_authenticated_disagree}
            trustedUserAgree={resolvedSummary.trusted_user_agree}
            trustedUserDisagree={resolvedSummary.trusted_user_disagree}
          />
          {#if resolvedSummary.agree_count > 0 && resolvedSummary.signal_quality_counts}
            {@const sq = resolvedSummary.signal_quality_counts}
            {#if sq.solo > 0 || sq.dominant > 0 || sq.mixed > 0}
              <div class="flex items-center gap-0.5">
                {#if sq.solo > 0}
                  <span
                    class="rounded bg-success-light px-1 py-0.5 text-[10px] font-medium text-success"
                    title={m.signal_quality_solo()}
                  >
                    {sq.solo}{m.signal_quality_solo_abbr()}
                  </span>
                {/if}
                {#if sq.dominant > 0}
                  <span
                    class="rounded bg-warning-light px-1 py-0.5 text-[10px] font-medium text-warning"
                    title={m.signal_quality_dominant()}
                  >
                    {sq.dominant}{m.signal_quality_dominant_abbr()}
                  </span>
                {/if}
                {#if sq.mixed > 0}
                  <span
                    class="rounded bg-warning-light px-1 py-0.5 text-[10px] font-medium text-warning"
                    title={m.signal_quality_mixed()}
                  >
                    {sq.mixed}{m.signal_quality_mixed_abbr()}
                  </span>
                {/if}
              </div>
            {/if}
          {/if}
        </div>

        <!--
          Expandable voter list (FR-039 / FR-040).
          Lazy-loaded — opening the <details> triggers the full
          getDetectionVoteSummary() fetch (see fullSummaryQuery above).
          The list is rendered for both the grid view and any consumer
          that mounts <DetectionCard> directly.
        -->
        <details
          class="text-xs"
          ontoggle={(event) => {
            votersExpanded = (event.currentTarget as HTMLDetailsElement).open;
          }}
        >
          <summary
            class="cursor-pointer list-none rounded px-1 py-0.5 text-xs text-stone-500 hover:text-stone-700"
            data-testid="voter-list-toggle"
          >
            {m.voter_list_toggle_label({
              count:
                resolvedSummary.agree_count +
                resolvedSummary.disagree_count +
                resolvedSummary.unsure_count,
            })}
          </summary>
          <div class="mt-1.5">
            {#if $fullSummaryQuery.isLoading}
              <p class="text-xs text-stone-400">{m.voter_list_toggle_loading()}</p>
            {:else if resolvedSummary.voters && resolvedSummary.voters.length > 0}
              <VoterList voters={resolvedSummary.voters} />
            {:else}
              <p class="text-xs text-stone-400" data-testid="voter-list-empty">
                {m.voter_list_empty()}
              </p>
            {/if}
          </div>
        </details>
      {/if}

      <!-- Source badge and reviewed_at -->
      <div class="flex items-center gap-1">
        <span class="rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-500">
          {getSourceLabel(detection.source)}
        </span>
        {#if detection.reviewed_at}
          <span
            class="text-xs text-stone-400"
            title={new Date(detection.reviewed_at).toLocaleString(getLocale())}
          >
            {m.detection_reviewed_on({
              date: new Date(detection.reviewed_at).toLocaleDateString(getLocale()),
            })}
          </span>
        {/if}
      </div>

      <!-- Species corrector -->
      <SpeciesCorrector
        currentTagId={detection.tag_id}
        {projectId}
        onChangeSpecies={handleChangeSpecies}
      />
    {/snippet}
  </ReviewCard>
</div>
