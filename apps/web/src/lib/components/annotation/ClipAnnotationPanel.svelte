<script lang="ts">
  import type { TagSummary, Note } from '$lib/types/annotation';
  import { getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  let {
    projectId,
    clipAnnotationId = null,
    /** Currently applied clip-level tags. Rendered as removable chips. */
    clipTags = [] as TagSummary[],
    /** Full list of tags available for this annotation project. */
    availableTags = [] as TagSummary[],
    /** Existing notes on the clip annotation (optional; for display only). */
    notes = [] as Note[],
    onAddTag,
    onRemoveTag,
    onAddNote,
  }: {
    projectId: string;
    clipAnnotationId?: string | null;
    clipTags?: TagSummary[];
    availableTags?: TagSummary[];
    notes?: Note[];
    onAddTag: (tagId: string) => void;
    onRemoveTag: (tagId: string) => void;
    onAddNote: (content: string) => void;
  } = $props();

  // projectId and clipAnnotationId are exposed as props for parent components that may need them for API calls.
  void projectId;
  void clipAnnotationId;

  let noteInput = $state('');

  // Group available tags by category for the Quick Tags section
  const speciesTags = $derived(availableTags.filter((t) => t.category === 'species'));
  const soundTypeTags = $derived(availableTags.filter((t) => t.category === 'sound_type'));
  const qualityTags = $derived(availableTags.filter((t) => t.category === 'quality'));

  // Set of active tag IDs for O(1) membership checks
  const activeTagIds = $derived(new Set(clipTags.map((t) => t.id)));

  function handleTagToggle(tagId: string) {
    if (activeTagIds.has(tagId)) {
      onRemoveTag(tagId);
    } else {
      onAddTag(tagId);
    }
  }

  function handleAddNote() {
    const trimmed = noteInput.trim();
    if (!trimmed) return;
    onAddNote(trimmed);
    noteInput = '';
  }

  function handleNoteKeydown(event: KeyboardEvent) {
    // Ctrl+Enter or Cmd+Enter submits the note
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      handleAddNote();
    }
  }

  function formatNoteDate(isoString: string): string {
    const date = new Date(isoString);
    return date.toLocaleString(getLocale(), {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }
</script>

<div class="panel">
  <!-- Applied clip tags — shown as removable chips when tags are active -->
  {#if clipTags.length > 0}
    <section class="section" aria-labelledby="applied-tags-heading">
      <h3 class="section-title" id="applied-tags-heading">{m.clip_panel_applied_tags()}</h3>
      <div class="chip-row" aria-label="Applied clip tags" aria-live="polite">
        {#each clipTags as tag (tag.id)}
          <button
            type="button"
            class="tag-chip tag-chip--{tag.category} tag-chip--removable"
            onclick={() => onRemoveTag(tag.id)}
            title="Remove {tag.name}"
            aria-label="Remove tag {tag.name}"
          >
            {tag.name}
            <span class="chip-remove" aria-hidden="true">&times;</span>
          </button>
        {/each}
      </div>
    </section>

    <div class="divider" role="separator"></div>
  {/if}

  <!-- Quick Tags section — all available tags grouped by category -->
  <section class="section" aria-labelledby="quick-tags-heading">
    <h3 class="section-title" id="quick-tags-heading">{m.clip_panel_quick_tags()}</h3>

    {#if availableTags.length === 0}
      <p class="empty-hint">No tags configured for this project.</p>
    {:else}
      <!-- Species -->
      {#if speciesTags.length > 0}
        <div class="tag-group">
          <span class="tag-group-label">{m.clip_panel_species()}</span>
          <div class="tag-buttons">
            {#each speciesTags as tag (tag.id)}
              <button
                type="button"
                class="tag-btn tag-btn--species"
                class:tag-btn--active={activeTagIds.has(tag.id)}
                onclick={() => handleTagToggle(tag.id)}
                aria-pressed={activeTagIds.has(tag.id)}
                title={activeTagIds.has(tag.id) ? `Remove ${tag.name}` : `Add ${tag.name}`}
              >
                {tag.name}
              </button>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Sound Type -->
      {#if soundTypeTags.length > 0}
        <div class="tag-group">
          <span class="tag-group-label">{m.clip_panel_sound_type()}</span>
          <div class="tag-buttons">
            {#each soundTypeTags as tag (tag.id)}
              <button
                type="button"
                class="tag-btn tag-btn--sound_type"
                class:tag-btn--active={activeTagIds.has(tag.id)}
                onclick={() => handleTagToggle(tag.id)}
                aria-pressed={activeTagIds.has(tag.id)}
                title={activeTagIds.has(tag.id) ? `Remove ${tag.name}` : `Add ${tag.name}`}
              >
                {tag.name}
              </button>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Quality -->
      {#if qualityTags.length > 0}
        <div class="tag-group">
          <span class="tag-group-label">{m.clip_panel_quality()}</span>
          <div class="tag-buttons">
            {#each qualityTags as tag (tag.id)}
              <button
                type="button"
                class="tag-btn tag-btn--quality"
                class:tag-btn--active={activeTagIds.has(tag.id)}
                onclick={() => handleTagToggle(tag.id)}
                aria-pressed={activeTagIds.has(tag.id)}
                title={activeTagIds.has(tag.id) ? `Remove ${tag.name}` : `Add ${tag.name}`}
              >
                {tag.name}
              </button>
            {/each}
          </div>
        </div>
      {/if}
    {/if}
  </section>

  <div class="divider" role="separator"></div>

  <!-- Notes section -->
  <section class="section" aria-labelledby="notes-heading">
    <h3 class="section-title" id="notes-heading">{m.clip_panel_notes()}</h3>

    <!-- Add note input -->
    <div class="note-input-row">
      <textarea
        class="note-textarea"
        placeholder="Add a note... (Ctrl+Enter to submit)"
        bind:value={noteInput}
        onkeydown={handleNoteKeydown}
        rows={2}
        aria-label="Note content"
      ></textarea>
      <button
        type="button"
        class="add-note-btn"
        onclick={handleAddNote}
        disabled={noteInput.trim() === ''}
        aria-label="Add note"
      >
        Add Note
      </button>
    </div>

    <!-- Existing notes -->
    {#if notes.length === 0}
      <p class="empty-hint">No notes yet.</p>
    {:else}
      <ul class="notes-list" aria-label="Clip notes">
        {#each notes as note (note.id)}
          {#if !note.is_review}
            <li class="note-item">
              <div class="note-meta">
                <span class="note-author" title="User ID: {note.created_by_id}">
                  Annotator
                </span>
                <time class="note-time" datetime={note.created_at}>
                  {formatNoteDate(note.created_at)}
                </time>
              </div>
              <p class="note-content">{note.content}</p>
            </li>
          {/if}
        {/each}
      </ul>
    {/if}
  </section>
</div>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 0;
    font-size: 0.8125rem;
    color: #111827;
  }

  /* ---- Section ---- */
  .section {
    padding: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .section-title {
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #6b7280;
    margin: 0 0 0.25rem;
  }

  .divider {
    height: 1px;
    background: #e5e7eb;
    margin: 0 0.75rem;
  }

  /* ---- Tag groups ---- */
  .tag-group {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .tag-group-label {
    font-size: 0.6875rem;
    font-weight: 500;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .tag-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
  }

  /* ---- Tag buttons ---- */
  .tag-btn {
    display: inline-flex;
    align-items: center;
    padding: 0.25rem 0.625rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
    border: 1.5px solid transparent;
    transition: all 0.1s ease;
    background: #f3f4f6;
    color: #374151;
    line-height: 1.4;
  }

  .tag-btn:hover {
    opacity: 0.85;
  }

  .tag-btn:focus-visible {
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
  }

  /* Species */
  .tag-btn--species {
    background: #f0fdf4;
    color: #15803d;
    border-color: #bbf7d0;
  }

  .tag-btn--species.tag-btn--active {
    background: #16a34a;
    color: #ffffff;
    border-color: #16a34a;
  }

  /* Sound type */
  .tag-btn--sound_type {
    background: #eff6ff;
    color: #1d4ed8;
    border-color: #bfdbfe;
  }

  .tag-btn--sound_type.tag-btn--active {
    background: #2563eb;
    color: #ffffff;
    border-color: #2563eb;
  }

  /* Quality */
  .tag-btn--quality {
    background: #fefce8;
    color: #a16207;
    border-color: #fde68a;
  }

  .tag-btn--quality.tag-btn--active {
    background: #ca8a04;
    color: #ffffff;
    border-color: #ca8a04;
  }

  /* ---- Applied tag chips row ---- */
  .chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
  }

  /* Base chip — used for applied (removable) tags */
  .tag-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.2rem 0.5rem;
    border-radius: 9999px;
    font-size: 0.6875rem;
    font-weight: 500;
    border: 1.5px solid transparent;
    line-height: 1.4;
  }

  /* Removable chip — rendered as a button */
  .tag-chip--removable {
    cursor: pointer;
    transition: opacity 0.1s ease, filter 0.1s ease;
  }

  .tag-chip--removable:hover {
    filter: brightness(0.92);
  }

  .tag-chip--removable:focus-visible {
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
  }

  .chip-remove {
    font-size: 0.875rem;
    line-height: 1;
    opacity: 0.65;
  }

  .tag-chip--removable:hover .chip-remove {
    opacity: 1;
  }

  /* Category colour tokens for chips */
  .tag-chip--species {
    background: #dcfce7;
    color: #166534;
    border-color: #bbf7d0;
  }

  .tag-chip--sound_type {
    background: #dbeafe;
    color: #1e40af;
    border-color: #bfdbfe;
  }

  .tag-chip--quality {
    background: #fef9c3;
    color: #854d0e;
    border-color: #fde68a;
  }

  /* ---- Note input ---- */
  .note-input-row {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .note-textarea {
    width: 100%;
    padding: 0.5rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.8125rem;
    font-family: inherit;
    resize: vertical;
    min-height: 3rem;
    outline: none;
    box-sizing: border-box;
    color: #111827;
    background: #fff;
    line-height: 1.4;
  }

  .note-textarea:focus {
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  .note-textarea::placeholder {
    color: #9ca3af;
  }

  .add-note-btn {
    align-self: flex-end;
    padding: 0.375rem 0.875rem;
    background: #2563eb;
    color: #fff;
    border: none;
    border-radius: 0.375rem;
    font-size: 0.8125rem;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.1s ease;
  }

  .add-note-btn:hover:not(:disabled) {
    background: #1d4ed8;
  }

  .add-note-btn:focus-visible {
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
  }

  .add-note-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  /* ---- Notes list ---- */
  .notes-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .note-item {
    padding: 0.5rem;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 0.375rem;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .note-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
  }

  .note-author {
    font-size: 0.6875rem;
    font-weight: 600;
    color: #374151;
  }

  .note-time {
    font-size: 0.6875rem;
    color: #9ca3af;
    white-space: nowrap;
  }

  .note-content {
    margin: 0;
    font-size: 0.8125rem;
    color: #374151;
    line-height: 1.45;
    word-break: break-word;
  }

  /* ---- Empty hint ---- */
  .empty-hint {
    margin: 0;
    font-size: 0.8125rem;
    color: #9ca3af;
    font-style: italic;
  }
</style>
