<script lang="ts">
  /**
   * SearchResultCard - Displays a single similarity search result with spectrogram.
   *
   * Wraps ReviewCard (shared component). On confirm, creates an annotation via
   * the search API. Reject is client-side state only.
   */

  import * as m from '$lib/paraglide/messages.js';
  import { createAnnotationFromSearch, rejectSearchResult } from '$lib/api/search';
  import type { SimilarityResult, SearchResultStatus } from '$lib/types/search';
  import ReviewCard from '$lib/components/common/ReviewCard.svelte';

  interface Props {
    projectId: string;
    result: SimilarityResult;
    tagId: string;
    status: SearchResultStatus;
    searchSessionId?: string;
    /** Highlight this card when it is keyboard-focused */
    isSelected?: boolean;
    onConfirm: () => void;
    onReject: () => void;
  }

  let { projectId, result, tagId, status, searchSessionId, isSelected = false, onConfirm, onReject }: Props = $props();

  let isConfirming = $state(false);
  let isRejecting = $state(false);

  const recordingName = $derived(result.recording_filename ?? result.recording_id.slice(0, 8) + '...');

  function getSimilarityBadgeClass(similarity: number): string {
    if (similarity >= 0.8) return 'bg-green-100 text-green-700';
    if (similarity >= 0.7) return 'bg-primary-100 text-primary-800';
    if (similarity >= 0.5) return 'bg-yellow-100 text-yellow-700';
    return 'bg-stone-100 text-stone-600';
  }

  async function handleConfirm() {
    if (isConfirming || status === 'confirmed') return;
    isConfirming = true;
    try {
      await createAnnotationFromSearch(projectId, {
        recording_id: result.recording_id,
        tag_id: tagId,
        start_time: result.start_time,
        end_time: result.end_time,
        confidence: result.similarity,
        search_session_id: searchSessionId,
      });
      onConfirm();
    } catch {
      // Silently fail — user can retry
    } finally {
      isConfirming = false;
    }
  }

  async function handleReject() {
    if (isRejecting || status === 'rejected') return;
    isRejecting = true;
    try {
      await rejectSearchResult(projectId, {
        recording_id: result.recording_id,
        tag_id: tagId,
        start_time: result.start_time,
        end_time: result.end_time,
        confidence: result.similarity,
        search_session_id: searchSessionId,
      });
      onReject();
    } catch (err) {
      console.error('Failed to reject:', err);
      // Still update UI even if API call fails
      onReject();
    } finally {
      isRejecting = false;
    }
  }
</script>

<ReviewCard
  {projectId}
  recordingId={result.recording_id}
  {recordingName}
  startTime={result.start_time}
  endTime={result.end_time}
  status={status as 'unreviewed' | 'confirmed' | 'rejected'}
  scoreValue={result.similarity}
  scoreLabel={m.search_similarity()}
  scoreBadgeClass={getSimilarityBadgeClass(result.similarity)}
  isLoading={isConfirming || isRejecting}
  {isSelected}
  onConfirm={handleConfirm}
  onReject={handleReject}
/>
