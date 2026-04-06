<script lang="ts">
  /**
   * FilenameCharGrid - Interactive character grid for selecting datetime parts in a filename.
   *
   * Allows drag-selection of character ranges in a filename string.
   * Each selected range can be assigned to a datetime part (Year, Month, Day, etc.).
   */
  import * as m from '$lib/paraglide/messages';

  type DatetimePart = 'Y' | 'M' | 'D' | 'h' | 'm' | 's';

  interface Props {
    filename: string;
    assignments: Map<DatetimePart, [number, number]>;
    onAssignmentsChange: (assignments: Map<DatetimePart, [number, number]>) => void;
  }

  let { filename, assignments, onAssignmentsChange }: Props = $props();

  const PART_COLORS: Record<DatetimePart, { bg: string; text: string; label: () => string }> = {
    Y: { bg: 'bg-primary-200', text: 'text-primary-900', label: () => m.datetime_config_year() },
    M: { bg: 'bg-green-200', text: 'text-green-900', label: () => m.datetime_config_month() },
    D: { bg: 'bg-orange-200', text: 'text-orange-900', label: () => m.datetime_config_day() },
    h: { bg: 'bg-red-200', text: 'text-red-900', label: () => m.datetime_config_hour() },
    m: { bg: 'bg-purple-200', text: 'text-purple-900', label: () => m.datetime_config_minute() },
    s: { bg: 'bg-teal-200', text: 'text-teal-900', label: () => m.datetime_config_second() },
  };

  const PART_KEYS: DatetimePart[] = ['Y', 'M', 'D', 'h', 'm', 's'];

  // Selection state
  let selectionStart = $state<number | null>(null);
  let selectionEnd = $state<number | null>(null);
  let isSelecting = $state(false);

  const currentSelectionRange = $derived(
    selectionStart !== null && selectionEnd !== null
      ? { min: Math.min(selectionStart, selectionEnd), max: Math.max(selectionStart, selectionEnd) }
      : null
  );

  const hasSelection = $derived(currentSelectionRange !== null);

  const sortedAssignments = $derived(
    ([...assignments.entries()] as [DatetimePart, [number, number]][])
      .sort((a, b) => a[1][0] - b[1][0])
  );

  function getCharColorClass(index: number): string {
    for (const part of PART_KEYS) {
      const range = assignments.get(part);
      if (range && index >= range[0] && index <= range[1]) {
        return `${PART_COLORS[part].bg} ${PART_COLORS[part].text}`;
      }
    }
    return 'bg-stone-100 text-stone-700';
  }

  function isInSelection(index: number): boolean {
    if (!currentSelectionRange) return false;
    return index >= currentSelectionRange.min && index <= currentSelectionRange.max;
  }

  function startSelection(index: number) {
    selectionStart = index;
    selectionEnd = index;
    isSelecting = true;
  }

  function extendSelection(index: number) {
    if (isSelecting) {
      selectionEnd = index;
    }
  }

  function endSelection() {
    isSelecting = false;
  }

  function assignPart(part: DatetimePart) {
    if (!currentSelectionRange) return;
    const newAssignments = new Map(assignments);
    newAssignments.set(part, [currentSelectionRange.min, currentSelectionRange.max]);
    onAssignmentsChange(newAssignments);
    selectionStart = null;
    selectionEnd = null;
  }

  function clearAssignment(part: DatetimePart) {
    const newAssignments = new Map(assignments);
    newAssignments.delete(part);
    onAssignmentsChange(newAssignments);
  }

  function clearAllAssignments() {
    onAssignmentsChange(new Map());
    selectionStart = null;
    selectionEnd = null;
  }

  // End selection when mouse is released anywhere in the document
  $effect(() => {
    const handler = () => { isSelecting = false; };
    document.addEventListener('mouseup', handler);
    return () => document.removeEventListener('mouseup', handler);
  });
</script>

<div>
  <!-- Color legend -->
  <div class="mb-3 flex flex-wrap gap-2">
    {#each PART_KEYS as part}
      <span
        class="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium {PART_COLORS[part].bg} {PART_COLORS[part].text}"
      >
        {PART_COLORS[part].label()}
      </span>
    {/each}
  </div>

  <!-- Filename character grid (drag to select) -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="overflow-x-auto rounded-t-md border border-stone-300 bg-stone-50 px-3 py-2 select-none"
    onmouseleave={() => { if (isSelecting) isSelecting = false; }}
  >
    <div class="flex flex-wrap font-mono text-sm leading-relaxed gap-0.5">
      {#each filename.split('') as char, i}
        <button
          type="button"
          class="inline-flex items-center justify-center w-6 h-7 border rounded-sm cursor-pointer transition-colors
            {getCharColorClass(i)}
            {isInSelection(i)
              ? 'ring-2 ring-primary-500 ring-inset border-primary-400'
              : 'border-transparent hover:border-stone-400'}"
          onmousedown={(e) => { e.preventDefault(); startSelection(i); }}
          onmouseenter={() => extendSelection(i)}
          onmouseup={() => endSelection()}
          aria-label="{char} at position {i}"
        >{char}</button>
      {/each}
    </div>
  </div>

  <!-- Assign part buttons -->
  <div class="rounded-b-md border border-t-0 border-stone-300 bg-surface-card px-3 py-2.5">
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-xs text-stone-500 shrink-0">{m.datetime_config_assign_part()}</span>
      {#each PART_KEYS as part}
        <button
          type="button"
          disabled={!hasSelection}
          onclick={() => assignPart(part)}
          class="inline-flex items-center rounded px-2 py-1 text-xs font-medium transition-colors
            {PART_COLORS[part].bg} {PART_COLORS[part].text}
            disabled:opacity-40 disabled:cursor-not-allowed
            hover:opacity-80 active:opacity-60"
        >
          {PART_COLORS[part].label()}
        </button>
      {/each}
      {#if assignments.size > 0}
        <button
          type="button"
          onclick={clearAllAssignments}
          class="inline-flex items-center rounded border border-stone-300 bg-surface-card px-2 py-1 text-xs font-medium text-stone-600 transition-colors hover:bg-stone-50 hover:text-red-600 hover:border-red-300"
        >
          {m.datetime_config_clear_all()}
        </button>
      {/if}
    </div>

    {#if !hasSelection && assignments.size === 0}
      <p class="mt-1.5 text-xs text-stone-400">{m.datetime_config_no_selection()}</p>
    {/if}
  </div>

  <!-- Assignment badges showing current assigned parts -->
  {#if sortedAssignments.length > 0}
    <div class="flex flex-wrap gap-2 mt-2">
      {#each sortedAssignments as [part, [start, end]]}
        <div
          class="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs {PART_COLORS[part].bg} {PART_COLORS[part].text}"
        >
          <span>{PART_COLORS[part].label()}: "{filename.slice(start, end + 1)}"</span>
          <button
            type="button"
            class="ml-1 hover:opacity-70 font-semibold"
            onclick={() => clearAssignment(part)}
            aria-label="Remove {PART_COLORS[part].label()} assignment"
          >x</button>
        </div>
      {/each}
    </div>
  {/if}
</div>
