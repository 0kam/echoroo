<script lang="ts">
  /**
   * Edit-recording modal.
   *
   * Presentational: two-way binds the note / time-expansion fields and
   * delegates persistence to the parent via `onSubmit`. The parent owns the
   * update mutation (and closes the modal on success) and controls the
   * `isSaving` in-flight flag.
   */

  import * as m from '$lib/paraglide/messages';

  let {
    editNote = $bindable(),
    editTimeExpansion = $bindable(),
    isSaving,
    onClose,
    onSubmit,
  }: {
    editNote: string;
    editTimeExpansion: number;
    isSaving: boolean;
    onClose: () => void;
    onSubmit: () => void;
  } = $props();

  function handleEditSubmit(e: Event) {
    e.preventDefault();
    onSubmit();
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
  class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
  onclick={onClose}
>
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="bg-surface-card rounded-lg shadow-xl p-6 w-full max-w-md"
    onclick={(e) => e.stopPropagation()}
  >
    <h3 class="text-lg font-semibold text-stone-800 mb-4">{m.recording_detail_edit_modal_title()}</h3>
    <form onsubmit={handleEditSubmit}>
      <div class="space-y-4 mb-6">
        <div>
          <label for="time-expansion" class="block text-sm font-medium text-stone-700 mb-1">
            {m.recording_detail_time_expansion_label()}
          </label>
          <input
            id="time-expansion"
            type="number"
            step="0.1"
            min="0.1"
            max="100"
            bind:value={editTimeExpansion}
            class="w-full px-3 py-2 border border-stone-300 rounded-md text-sm bg-surface-card focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
          <p class="mt-1 text-xs text-stone-500">{m.recording_detail_time_expansion_hint()}</p>
        </div>
        <div>
          <label for="note" class="block text-sm font-medium text-stone-700 mb-1">
            {m.recording_detail_notes_label()}
          </label>
          <textarea
            id="note"
            bind:value={editNote}
            rows="3"
            class="w-full px-3 py-2 border border-stone-300 rounded-md text-sm bg-surface-card focus:outline-none focus:ring-2 focus:ring-primary-500"
          ></textarea>
        </div>
      </div>
      <div class="flex justify-end gap-3">
        <button
          type="button"
          onclick={onClose}
          class="px-4 py-2 text-sm font-medium border border-stone-300 rounded-md hover:bg-stone-50"
        >
          {m.recording_detail_cancel()}
        </button>
        <button
          type="submit"
          disabled={isSaving}
          class="px-4 py-2 text-sm font-medium bg-success text-white rounded-md hover:opacity-90 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {isSaving ? m.recording_detail_saving() : m.recording_detail_save()}
        </button>
      </div>
    </form>
  </div>
</div>
