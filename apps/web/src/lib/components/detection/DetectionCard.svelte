<script lang="ts">
  /**
   * DetectionCard - Compact card showing a single detection with review actions.
   *
   * Wraps ReviewCard (shared component) and adds detection-specific features:
   * species name/confidence header, source badge, reviewed_at metadata,
   * and SpeciesCorrector for reassigning the species tag.
   */

  import type { Detection } from '$lib/types/detection';
  import * as m from '$lib/paraglide/messages';
  import { getLocale } from '$lib/paraglide/runtime';
  import ReviewCard from '$lib/components/common/ReviewCard.svelte';
  import SpeciesCorrector from './SpeciesCorrector.svelte';

  interface Props {
    detection: Detection;
    projectId: string;
    isSelected?: boolean;
    isLoading?: boolean;
    /** Whether this card's audio is currently playing (controlled by parent navigation) */
    externalIsPlaying?: boolean;
    /** Whether the external player is loading audio for this card */
    externalIsLoadingAudio?: boolean;
    /** Callback when the play button is clicked (delegates to parent's player) */
    onPlayToggle?: () => void;
    onConfirm: (detectionId: string, startTime: number, endTime: number) => void;
    onReject: (detectionId: string) => void;
    onChangeSpecies: (detectionId: string, newTagId: string) => void;
  }

  let {
    detection,
    projectId,
    isSelected = false,
    isLoading = false,
    externalIsPlaying,
    externalIsLoadingAudio,
    onPlayToggle,
    onConfirm,
    onReject,
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
        ? 'bg-green-100 text-green-700'
        : confidencePercent >= 50
          ? 'bg-yellow-100 text-yellow-700'
          : 'bg-red-100 text-red-700'
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

  function handleConfirm() {
    onConfirm(detection.id, detection.start_time, detection.end_time);
  }

  function handleReject() {
    onReject(detection.id);
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
    {externalIsPlaying}
    {externalIsLoadingAudio}
    {onPlayToggle}
    onConfirm={handleConfirm}
    onReject={handleReject}
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
