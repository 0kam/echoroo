<script lang="ts">
  /**
   * AnnotationList — list of TimeRangeAnnotations within a segment.
   *
   * Renders rows sorted by start_time_sec with species label, range, and
   * delete button. Parent owns the selection and mutations.
   */
  import * as m from '$lib/paraglide/messages';
  import type { TimeRangeAnnotation } from '$lib/types/annotation-set';
  import { formatSpeciesName } from '$lib/utils/speciesFormatters';

  interface Props {
    annotations: TimeRangeAnnotation[];
    selectedId: string | null;
    /**
     * Start of the segment in absolute recording seconds. Retained for
     * backwards compatibility; annotation times are already stored relative
     * to the segment start so callers can pass 0 if they prefer.
     */
    segmentStart?: number;
    isBusy?: boolean;
    onSelect: (id: string) => void;
    onDelete: (id: string) => void;
  }

  let {
    annotations,
    selectedId,
    segmentStart: _segmentStart = 0,
    isBusy = false,
    onSelect,
    onDelete,
  }: Props = $props();

  const sorted = $derived(
    [...annotations].sort((a, b) => a.start_time_sec - b.start_time_sec),
  );

  function fmt(sec: number): string {
    // Annotation times are stored relative to the segment start already.
    return sec.toFixed(2);
  }

  function speciesLabel(a: TimeRangeAnnotation): string {
    return formatSpeciesName(a.species_common_name, a.species_scientific_name);
  }

  function colorForSpecies(id: string): string {
    let hash = 0;
    for (let i = 0; i < id.length; i++) {
      hash = (hash * 31 + id.charCodeAt(i)) | 0;
    }
    const hue = Math.abs(hash) % 360;
    return `hsl(${hue}, 65%, 45%)`;
  }
</script>

<div class="flex h-full flex-col">
  <div class="mb-2 flex items-baseline justify-between gap-2">
    <h3 class="text-sm font-semibold text-stone-900 dark:text-stone-100">
      {m.annotation_editor_annotations_title()}
    </h3>
    <span class="text-xs text-stone-500">
      {m.annotation_editor_annotations_count({ count: sorted.length })}
    </span>
  </div>

  {#if sorted.length === 0}
    <p class="rounded-lg border border-dashed border-stone-300 p-4 text-center text-xs text-stone-400 dark:border-stone-700">
      {m.annotation_editor_annotations_empty()}
    </p>
  {:else}
    <ul class="flex flex-col gap-1.5" role="list">
      {#each sorted as a (a.id)}
        {@const isSel = a.id === selectedId}
        {@const color = colorForSpecies(a.species_id)}
        <li>
          <div
            class="group relative flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-left transition-colors"
            class:border-stone-200={!isSel}
            class:bg-white={!isSel}
            class:dark:border-stone-700={!isSel}
            class:dark:bg-stone-800={!isSel}
            class:ring-2={isSel}
            style:--tw-ring-color={isSel ? color : 'transparent'}
            style:border-color={isSel ? color : undefined}
            style:background-color={isSel ? `${color}14` : undefined}
          >
            <!-- Color swatch -->
            <span
              class="h-2.5 w-2.5 flex-shrink-0 rounded-sm"
              style:background-color={color}
              aria-hidden="true"
            ></span>

            <!-- Clickable main area -->
            <button
              type="button"
              class="min-w-0 flex-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
              aria-label={speciesLabel(a)}
              aria-pressed={isSel}
              onclick={() => onSelect(a.id)}
            >
              <div class="truncate text-xs font-medium text-stone-900 dark:text-stone-100">
                {speciesLabel(a)}
              </div>
              <div class="mt-0.5 text-[11px] text-stone-500 tabular-nums">
                {fmt(a.start_time_sec)}s – {fmt(a.end_time_sec)}s
                {#if a.confidence != null}
                  · {Math.round(a.confidence * 100)}%
                {/if}
                {#if a.note_count > 0}
                  · {a.note_count} {m.annotation_editor_annotation_notes()}
                {/if}
              </div>
            </button>

            <!-- Delete button -->
            <button
              type="button"
              class="flex-shrink-0 rounded p-1 text-stone-400 opacity-0 transition-opacity hover:bg-danger-light hover:text-danger group-hover:opacity-100 focus:opacity-100 focus-visible:opacity-100 disabled:cursor-not-allowed"
              aria-label={m.annotation_editor_annotation_delete()}
              title={m.annotation_editor_annotation_delete()}
              disabled={isBusy}
              onclick={() => onDelete(a.id)}
            >
              <svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path
                  fill-rule="evenodd"
                  clip-rule="evenodd"
                  d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z"
                />
              </svg>
            </button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>
