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
  import ReviewCard from '$lib/components/common/ReviewCard.svelte';
  import SpeciesCorrector from './SpeciesCorrector.svelte';

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
  const tagName = $derived(
    detection.tag?.common_name ?? detection.tag?.name ?? 'Unidentified'
  );

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
        return 'Human';
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
</script>

<!-- Wrapper applies the scale animation on top of ReviewCard -->
<div
  class="transition-transform duration-300 ease-in-out {justUpdated ? 'scale-[1.02]' : ''}"
  role="article"
  aria-label="Detection: {tagName}"
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
    {voteSummary}
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
            title="Model confidence"
          >
            {confidencePercent}%
          </span>
        {/if}
      </div>
    {/snippet}

    {#snippet extraBody()}
      <!-- Vote summary indicator -->
      {#if voteSummary && (voteSummary.agree_count + voteSummary.disagree_count + voteSummary.unsure_count) > 0}
        <div class="flex flex-wrap items-center gap-1.5">
          <!-- Consensus badge -->
          <span
            class="rounded border px-1.5 py-0.5 text-xs font-medium {getConsensusStatusBadgeClass(voteSummary.consensus_status)}"
          >
            {getConsensusStatusLabel(voteSummary.consensus_status)}
          </span>
          <!-- Vote ratio -->
          <span class="text-xs text-stone-400">
            {m.vote_summary_ratio({ agree: voteSummary.agree_count, total: voteSummary.agree_count + voteSummary.disagree_count + voteSummary.unsure_count })}
          </span>
          <!-- Signal quality breakdown (only when there are agree votes with quality data) -->
          {#if voteSummary.agree_count > 0 && voteSummary.signal_quality_counts}
            {@const sq = voteSummary.signal_quality_counts}
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
