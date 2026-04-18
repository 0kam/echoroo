<script lang="ts">
  /**
   * NotesPanel — notes for the segment or the currently selected annotation.
   *
   * The editor passes the appropriate list and mutation callbacks. This
   * component does not know whether the note target is a segment or an
   * annotation — it just renders the list and an "add note" form.
   */
  import * as m from '$lib/paraglide/messages';
  import type { AnnotationNote } from '$lib/types/annotation-set';

  interface Props {
    title: string;
    notes: AnnotationNote[];
    /** Disable interaction while a mutation is pending. */
    isBusy?: boolean;
    onAddNote: (content: string, isIssue: boolean) => Promise<void> | void;
  }

  let { title, notes, isBusy = false, onAddNote }: Props = $props();

  let content = $state('');
  let isIssue = $state(false);

  async function submit() {
    const trimmed = content.trim();
    if (!trimmed || isBusy) return;
    const snapshot = { content: trimmed, isIssue };
    content = '';
    isIssue = false;
    try {
      await onAddNote(snapshot.content, snapshot.isIssue);
    } catch {
      // Restore draft on failure so user can retry.
      content = snapshot.content;
      isIssue = snapshot.isIssue;
    }
  }

  function handleKeyDown(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      void submit();
    }
  }

  function formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return iso;
    }
  }
</script>

<div class="flex flex-col">
  <h4 class="mb-1.5 text-xs font-semibold uppercase tracking-wide text-stone-500">
    {title}
  </h4>

  {#if notes.length === 0}
    <p class="rounded-lg border border-dashed border-stone-300 p-2 text-center text-[11px] text-stone-400 dark:border-stone-700">
      {m.annotation_editor_notes_empty()}
    </p>
  {:else}
    <ul class="mb-2 flex flex-col gap-1.5" role="list">
      {#each notes as note (note.id)}
        <li
          class="rounded-md border border-stone-200 bg-stone-50 p-2 text-xs dark:border-stone-700 dark:bg-stone-800/40"
        >
          <div class="flex items-center justify-between gap-2 text-[10px] text-stone-500">
            <time datetime={note.created_at}>{formatDate(note.created_at)}</time>
            {#if note.is_issue}
              <span
                class="inline-flex items-center rounded-full bg-[rgb(var(--color-warning-light))] px-1.5 py-0.5 text-[9px] font-medium text-[rgb(var(--color-warning))]"
              >
                {m.annotation_editor_notes_issue_badge()}
              </span>
            {/if}
          </div>
          <p class="mt-0.5 whitespace-pre-wrap break-words text-stone-800 dark:text-stone-100">
            {note.content}
          </p>
        </li>
      {/each}
    </ul>
  {/if}

  <textarea
    class="block w-full resize-none rounded-md border border-stone-300 bg-white px-2 py-1.5 text-xs shadow-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
    rows="2"
    maxlength="5000"
    placeholder={m.annotation_editor_notes_placeholder()}
    bind:value={content}
    onkeydown={handleKeyDown}
    aria-label={m.annotation_editor_notes_placeholder()}
  ></textarea>

  <div class="mt-1.5 flex items-center justify-between gap-2">
    <label class="inline-flex items-center gap-1 text-[11px] text-stone-600 dark:text-stone-300">
      <input
        type="checkbox"
        bind:checked={isIssue}
        class="h-3 w-3 rounded border-stone-300 text-primary-600 focus:ring-primary-500 dark:border-stone-600 dark:bg-stone-800"
      />
      {m.annotation_editor_notes_issue_label()}
    </label>

    <div class="flex items-center gap-1.5">
      <span class="text-[10px] text-stone-400">
        {m.annotation_editor_notes_submit_hint()}
      </span>
      <button
        type="button"
        class="rounded-md bg-primary-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
        disabled={isBusy || content.trim().length === 0}
        onclick={submit}
      >
        {m.annotation_editor_notes_submit()}
      </button>
    </div>
  </div>
</div>
