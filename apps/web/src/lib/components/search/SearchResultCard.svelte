<script lang="ts">
  /**
   * SearchResultCard - Displays a single similarity search result with spectrogram.
   *
   * Wraps ReviewCard (shared component). Voting (Agree/Disagree/Unsure) is
   * handled by the parent ResultsPanel via TanStack Query mutations; this card
   * only forwards vote callbacks and displays the vote summary.
   */

  import * as m from '$lib/paraglide/messages.js';
  import type { SimilarityResult } from '$lib/types/search';
  import type { VoteSummary, VoteValue, SignalQuality } from '$lib/types/detection';
  import ReviewCard from '$lib/components/common/ReviewCard.svelte';

  interface Props {
    projectId: string;
    result: SimilarityResult;
    searchSessionId?: string;
    /** Highlight this card when it is keyboard-focused */
    isSelected?: boolean;
    /** Whether this card's audio is currently playing (controlled by parent navigation) */
    externalIsPlaying?: boolean;
    /** Whether the external player is loading audio for this card */
    externalIsLoadingAudio?: boolean;
    /** Callback when the play button is clicked (delegates to parent's player) */
    onPlayToggle?: () => void;
    /** Current vote summary (null when not yet loaded) */
    voteSummary: VoteSummary | null;
    /** Whether a vote mutation is in flight for this card */
    isVoting?: boolean;
    /** Called when the user casts an agree vote with signal quality */
    onAgree: (signalQuality: SignalQuality) => void;
    /** Called when the user casts a non-agree vote */
    onVote: (vote: VoteValue) => void;
    /** Called when the user removes their current vote */
    onRemoveVote: () => void;
  }

  let {
    projectId,
    result,
    searchSessionId: _searchSessionId,
    isSelected = false,
    externalIsPlaying,
    externalIsLoadingAudio,
    onPlayToggle,
    voteSummary,
    isVoting = false,
    onAgree,
    onVote,
    onRemoveVote,
  }: Props = $props();

  const recordingName = $derived(result.recording_filename ?? result.recording_id.slice(0, 8) + '...');

  function getSimilarityBadgeClass(similarity: number): string {
    if (similarity >= 0.8) return 'bg-green-100 text-green-700';
    if (similarity >= 0.7) return 'bg-primary-100 text-primary-800';
    if (similarity >= 0.5) return 'bg-yellow-100 text-yellow-700';
    return 'bg-stone-100 text-stone-600';
  }
</script>

<ReviewCard
  {projectId}
  recordingId={result.recording_id}
  {recordingName}
  startTime={result.start_time}
  endTime={result.end_time}
  status="unreviewed"
  scoreValue={result.similarity}
  scoreLabel={m.search_similarity()}
  scoreBadgeClass={getSimilarityBadgeClass(result.similarity)}
  isLoading={isVoting}
  {isSelected}
  {externalIsPlaying}
  {externalIsLoadingAudio}
  {onPlayToggle}
  {voteSummary}
  {onAgree}
  {onVote}
  {onRemoveVote}
/>
