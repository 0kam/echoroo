<script lang="ts">
  /**
   * SegmentNavigator — top navigation bar for the AnnotationEditor.
   *
   * Shows the current segment position within the set plus primary action
   * buttons: previous / next / skip / complete. The editor owns the
   * mutation logic; this component is pure UI + callbacks.
   */
  import { onMount, onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages';
  import type { AnnotationSegmentStatus } from '$lib/types/annotation-set';
  import {
    getAnnotationSegmentStatusLabel,
    getAnnotationSegmentStatusClass,
  } from '$lib/utils/statusFormatters';

  interface Props {
    setName: string;
    backHref: string;
    currentIndex: number; // zero-based; display as +1
    totalSegments: number;
    status: AnnotationSegmentStatus;
    isEmpty: boolean;
    annotationCount: number;
    hasPrevious: boolean;
    hasNext: boolean;
    /** Disable mutation buttons while a request is in flight. */
    isBusy?: boolean;
    onPrevious: () => void;
    onNext: () => void;
    onSkip: () => void;
    onComplete: () => void;
    onMarkNoVocalization: () => void;
    onClearNoVocalization: () => void;
  }

  let {
    setName,
    backHref,
    currentIndex,
    totalSegments,
    status,
    isEmpty,
    annotationCount,
    hasPrevious,
    hasNext,
    isBusy = false,
    onPrevious,
    onNext,
    onSkip,
    onComplete,
    onMarkNoVocalization,
    onClearNoVocalization,
  }: Props = $props();

  const progressPercent = $derived(
    totalSegments > 0 ? Math.round(((currentIndex + 1) / totalSegments) * 100) : 0,
  );

  function handleKeyDown(e: KeyboardEvent) {
    // Avoid swallowing input in editable fields.
    const target = e.target as HTMLElement | null;
    if (target) {
      const tag = target.tagName;
      if (
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        tag === 'SELECT' ||
        target.isContentEditable
      ) {
        return;
      }
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      onComplete();
      return;
    }
    // Plain ← / → work as quick nav; Alt+← / Alt+→ are also supported and
    // advertised in the button tooltips. Ignore other modifier combos so we
    // don't hijack browser shortcuts.
    const modified = e.ctrlKey || e.metaKey || e.shiftKey;
    const isPrev = !modified && e.key === 'ArrowLeft';
    const isNext = !modified && e.key === 'ArrowRight';
    const isAltPrev = e.altKey && !e.ctrlKey && !e.metaKey && e.key === 'ArrowLeft';
    const isAltNext = e.altKey && !e.ctrlKey && !e.metaKey && e.key === 'ArrowRight';
    if ((isPrev || isAltPrev) && hasPrevious) {
      e.preventDefault();
      onPrevious();
      return;
    }
    if ((isNext || isAltNext) && hasNext) {
      e.preventDefault();
      onNext();
      return;
    }
  }

  onMount(() => window.addEventListener('keydown', handleKeyDown));
  onDestroy(() => window.removeEventListener('keydown', handleKeyDown));

  function statusLabel(s: AnnotationSegmentStatus): string {
    return getAnnotationSegmentStatusLabel(s, {
      unannotated: m.annotation_sets_segment_status_unannotated,
      annotated: m.annotation_sets_segment_status_annotated,
      skipped: m.annotation_sets_segment_status_skipped,
    });
  }

  function statusClass(s: AnnotationSegmentStatus): string {
    return getAnnotationSegmentStatusClass(s);
  }
</script>

<nav
  class="flex flex-wrap items-center gap-3 border-b border-stone-200 bg-surface-card px-4 py-2 dark:border-stone-700"
  aria-label="Segment navigator"
>
  <!-- Back link -->
  <a
    href={backHref}
    class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm text-stone-600 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-800"
  >
    <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      <path
        fill-rule="evenodd"
        clip-rule="evenodd"
        d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z"
      />
    </svg>
    <span class="hidden sm:inline">{m.annotation_editor_back()}</span>
  </a>

  <!-- Set name + status -->
  <div class="min-w-0 flex-1">
    <div class="flex items-center gap-2">
      <span class="truncate text-sm font-semibold text-stone-900 dark:text-stone-100" title={setName}>
        {setName}
      </span>
      <span
        class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {statusClass(status)}"
      >
        {statusLabel(status)}
      </span>
      {#if isEmpty}
        <span
          class="inline-flex items-center rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-500 dark:bg-stone-800 dark:text-stone-400"
        >
          {m.annotation_sets_segment_is_empty()}
        </span>
      {/if}
    </div>

    <!-- Progress bar -->
    <div class="mt-1 flex items-center gap-2">
      <div
        class="h-1 flex-1 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-700"
        role="progressbar"
        aria-valuenow={progressPercent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          class="h-full rounded-full bg-primary-500 transition-all"
          style:width="{progressPercent}%"
        ></div>
      </div>
      <span class="whitespace-nowrap text-xs text-stone-500 tabular-nums">
        {m.annotation_editor_progress({
          current: String(currentIndex + 1),
          total: String(totalSegments),
        })}
      </span>
    </div>
  </div>

  <!-- Action buttons -->
  <div class="flex flex-shrink-0 items-center gap-1.5">
    <button
      type="button"
      class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-stone-300 bg-white text-stone-700 hover:bg-stone-50 disabled:opacity-40 disabled:cursor-not-allowed dark:border-stone-600 dark:bg-stone-800 dark:text-stone-200 dark:hover:bg-stone-700"
      aria-label={m.annotation_editor_previous()}
      title="{m.annotation_editor_previous()} (Alt+←)"
      disabled={!hasPrevious || isBusy}
      onclick={onPrevious}
    >
      <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
        <path
          fill-rule="evenodd"
          clip-rule="evenodd"
          d="M12.79 5.23a.75.75 0 01-.02 1.06L8.832 10l3.938 3.71a.75.75 0 11-1.04 1.08l-4.5-4.25a.75.75 0 010-1.08l4.5-4.25a.75.75 0 011.06.02z"
        />
      </svg>
    </button>

    <button
      type="button"
      class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-stone-300 bg-white text-stone-700 hover:bg-stone-50 disabled:opacity-40 disabled:cursor-not-allowed dark:border-stone-600 dark:bg-stone-800 dark:text-stone-200 dark:hover:bg-stone-700"
      aria-label={m.annotation_editor_next()}
      title="{m.annotation_editor_next()} (Alt+→)"
      disabled={!hasNext || isBusy}
      onclick={onNext}
    >
      <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
        <path
          fill-rule="evenodd"
          clip-rule="evenodd"
          d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z"
        />
      </svg>
    </button>

    <button
      type="button"
      class="inline-flex items-center gap-1 rounded-md border border-stone-300 bg-white px-2.5 py-1 text-xs font-medium text-stone-700 hover:bg-stone-50 disabled:opacity-50 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-200 dark:hover:bg-stone-700"
      disabled={isBusy}
      onclick={onSkip}
    >
      {m.annotation_editor_skip()}
    </button>

    {#if isEmpty}
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-800/40 dark:bg-amber-900/20 dark:text-amber-300 dark:hover:bg-amber-900/40"
        disabled={isBusy}
        onclick={onClearNoVocalization}
      >
        {m.annotation_editor_clear_empty()}
      </button>
    {:else}
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded-md border border-stone-300 bg-white px-2.5 py-1 text-xs font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-200 dark:hover:bg-stone-700"
        disabled={isBusy || annotationCount > 0}
        title={annotationCount > 0
          ? m.annotation_editor_no_vocalization_error()
          : m.annotation_editor_no_vocalization()}
        onclick={onMarkNoVocalization}
      >
        {m.annotation_editor_no_vocalization()}
      </button>
    {/if}

    <button
      type="button"
      class="inline-flex items-center gap-1.5 rounded-md bg-[rgb(var(--color-success))] px-3 py-1 text-xs font-semibold text-white shadow-sm hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      title={m.annotation_editor_complete_title()}
      disabled={isBusy}
      onclick={onComplete}
    >
      <svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
        <path
          fill-rule="evenodd"
          clip-rule="evenodd"
          d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"
        />
      </svg>
      <span class="hidden md:inline">{m.annotation_editor_complete()}</span>
      <kbd class="rounded border border-white/30 bg-white/15 px-1 py-0.5 text-[10px] font-mono">
        Ctrl+↵
      </kbd>
    </button>
  </div>
</nav>
