<script lang="ts">
  import type { SoundEventAnnotation } from '$lib/types/annotation';
  import { getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  export let annotations: SoundEventAnnotation[] = [];
  export let selectedAnnotationId: string | null = null;
  export let onSelect: (id: string) => void;
  export let onDelete: (id: string) => void;

  // ============================================================
  // Helpers
  // ============================================================

  /**
   * Format seconds as "M:SS.mm"
   * e.g. 2.5 => "0:02.50", 65.3 => "1:05.30"
   */
  function formatTime(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    const sPadded = s.toFixed(2).padStart(5, '0');
    return `${m}:${sPadded}`;
  }

  function getTimeRange(annotation: SoundEventAnnotation): { start: number; end: number } {
    if (annotation.geometry.type === 'BoundingBox') {
      // coordinates = [time_start, freq_low, time_end, freq_high]
      return {
        start: annotation.geometry.coordinates[0] ?? 0,
        end: annotation.geometry.coordinates[2] ?? 0,
      };
    } else {
      // TimeInterval: coordinates = [time_start, time_end]
      return {
        start: annotation.geometry.coordinates[0] ?? 0,
        end: annotation.geometry.coordinates[1] ?? 0,
      };
    }
  }

  function getFreqRange(annotation: SoundEventAnnotation): string | null {
    if (annotation.geometry.type !== 'BoundingBox') return null;
    // coordinates = [time_start, freq_low, time_end, freq_high]
    const freqLow  = Math.round(annotation.geometry.coordinates[1] ?? 0);
    const freqHigh = Math.round(annotation.geometry.coordinates[3] ?? 0);
    return `${freqLow.toLocaleString(getLocale())}\u2013${freqHigh.toLocaleString(getLocale())} Hz`;
  }

  function getTagColor(category: string): { bg: string; text: string } {
    switch (category) {
      case 'species':    return { bg: '#dcfce7', text: '#15803d' };
      case 'sound_type': return { bg: '#dbeafe', text: '#1d4ed8' };
      case 'quality':    return { bg: '#fef9c3', text: '#a16207' };
      default:           return { bg: '#f3f4f6', text: '#374151' };
    }
  }

  // Sort annotations by start time
  $: sortedAnnotations = [...annotations].sort((a, b) => {
    const aTime = getTimeRange(a).start;
    const bTime = getTimeRange(b).start;
    return aTime - bTime;
  });
</script>

<div class="annotation-list">
  {#if sortedAnnotations.length === 0}
    <div class="empty-state">
      <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round"
          d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
      </svg>
      <p class="empty-title">{m.annotation_list_no_annotations()}</p>
      <p class="empty-subtitle">{m.annotation_list_draw_hint()}</p>
    </div>
  {:else}
    <ul class="annotation-items" role="listbox" aria-label="Sound event annotations">
      {#each sortedAnnotations as annotation (annotation.id)}
        {@const timeRange = getTimeRange(annotation)}
        {@const freqRange = getFreqRange(annotation)}
        {@const isSelected = annotation.id === selectedAnnotationId}

        <!-- svelte-ignore a11y-click-events-have-key-events -->
        <li
          class="annotation-item"
          class:selected={isSelected}
          role="option"
          aria-selected={isSelected}
          on:click={() => onSelect(annotation.id)}
        >
          <!-- Left: geometry icon -->
          <div class="icon-col" aria-hidden="true">
            {#if annotation.geometry.type === 'BoundingBox'}
              <!-- Rectangle icon -->
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" class="geo-icon">
                <rect x="1.5" y="3.5" width="13" height="9" rx="1"/>
              </svg>
            {:else}
              <!-- Time interval icon: horizontal lines -->
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" class="geo-icon">
                <line x1="1.5" y1="5" x2="14.5" y2="5"/>
                <line x1="1.5" y1="8" x2="14.5" y2="8"/>
                <line x1="1.5" y1="11" x2="14.5" y2="11"/>
              </svg>
            {/if}
          </div>

          <!-- Center: annotation details -->
          <div class="details-col">
            <!-- Time range -->
            <div class="time-row">
              <span class="time-label">{formatTime(timeRange.start)} &ndash; {formatTime(timeRange.end)}</span>
              {#if annotation.source === 'model'}
                <span class="source-badge model">{m.annotation_list_source_ai()}</span>
              {:else}
                <span class="source-badge human">{m.annotation_list_source_human()}</span>
              {/if}
            </div>

            <!-- Frequency range (BoundingBox only) -->
            {#if freqRange}
              <div class="freq-row">{freqRange}</div>
            {/if}

            <!-- Tags -->
            {#if annotation.tags.length > 0}
              <div class="tags-row">
                {#each annotation.tags as tag (tag.id)}
                  {@const colors = getTagColor(tag.category)}
                  <span
                    class="tag-chip"
                    style="background-color: {colors.bg}; color: {colors.text};"
                  >
                    {tag.name}
                  </span>
                {/each}
              </div>
            {/if}
          </div>

          <!-- Right: delete button -->
          <button
            class="delete-btn"
            title={m.annotation_list_delete_title()}
            aria-label={m.annotation_list_delete_aria()}
            on:click|stopPropagation={() => onDelete(annotation.id)}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" class="delete-icon">
              <path stroke-linecap="round" d="M4 4l8 8M12 4l-8 8"/>
            </svg>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .annotation-list {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  /* ---- Empty state ---- */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2rem 1rem;
    text-align: center;
    color: #9ca3af;
    gap: 0.25rem;
  }

  .empty-icon {
    width: 2.5rem;
    height: 2.5rem;
    margin-bottom: 0.5rem;
    opacity: 0.5;
  }

  .empty-title {
    font-size: 0.875rem;
    font-weight: 500;
    color: #6b7280;
    margin: 0;
  }

  .empty-subtitle {
    font-size: 0.75rem;
    color: #9ca3af;
    margin: 0;
  }

  /* ---- List ---- */
  .annotation-items {
    list-style: none;
    margin: 0;
    padding: 0.25rem;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    overflow-y: auto;
    flex: 1;
  }

  /* ---- Item ---- */
  .annotation-item {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    padding: 0.5rem 0.5rem 0.5rem 0.5rem;
    border-radius: 0.375rem;
    border: 1px solid #e5e7eb;
    background: #fff;
    cursor: pointer;
    transition: background-color 0.1s ease, border-color 0.1s ease;
  }

  .annotation-item:hover {
    background-color: #f9fafb;
    border-color: #d1d5db;
  }

  .annotation-item.selected {
    background-color: #eff6ff;
    border-color: #93c5fd;
  }

  /* ---- Geometry icon ---- */
  .icon-col {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    padding-top: 0.125rem;
  }

  .geo-icon {
    width: 1rem;
    height: 1rem;
    color: #6b7280;
  }

  /* ---- Details ---- */
  .details-col {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .time-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .time-label {
    font-size: 0.8125rem;
    font-weight: 500;
    color: #111827;
    font-variant-numeric: tabular-nums;
  }

  .freq-row {
    font-size: 0.6875rem;
    color: #6b7280;
  }

  /* ---- Source badges ---- */
  .source-badge {
    font-size: 0.625rem;
    font-weight: 600;
    padding: 0.0625rem 0.375rem;
    border-radius: 9999px;
    letter-spacing: 0.025em;
    text-transform: uppercase;
  }

  .source-badge.human {
    background-color: #f0fdf4;
    color: #166534;
    border: 1px solid #bbf7d0;
  }

  .source-badge.model {
    background-color: #faf5ff;
    color: #6b21a8;
    border: 1px solid #e9d5ff;
  }

  /* ---- Tags ---- */
  .tags-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
  }

  .tag-chip {
    font-size: 0.6875rem;
    font-weight: 500;
    padding: 0.0625rem 0.375rem;
    border-radius: 9999px;
    white-space: nowrap;
  }

  /* ---- Delete button ---- */
  .delete-btn {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.25rem;
    height: 1.25rem;
    border: none;
    background: transparent;
    border-radius: 9999px;
    cursor: pointer;
    color: #9ca3af;
    padding: 0;
    transition: background-color 0.1s ease, color 0.1s ease;
  }

  .delete-btn:hover {
    background-color: #fee2e2;
    color: #dc2626;
  }

  .delete-icon {
    width: 0.75rem;
    height: 0.75rem;
  }
</style>
