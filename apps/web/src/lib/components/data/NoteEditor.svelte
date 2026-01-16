<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  export let value: string = '';
  export let placeholder: string = 'Add a note...';
  export let disabled: boolean = false;
  export let maxLength: number = 2000;

  const dispatch = createEventDispatcher<{ save: string; cancel: void }>();

  let isEditing = false;
  let editValue = value;

  function startEdit() {
    if (disabled) return;
    editValue = value;
    isEditing = true;
  }

  function save() {
    dispatch('save', editValue);
    isEditing = false;
  }

  function cancel() {
    editValue = value;
    isEditing = false;
    dispatch('cancel');
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      cancel();
    } else if (event.key === 'Enter' && event.ctrlKey) {
      save();
    }
  }

  // Update editValue when value prop changes
  $: if (!isEditing) editValue = value;
</script>

<div class="note-editor">
  {#if isEditing}
    <div class="edit-mode">
      <textarea
        bind:value={editValue}
        {placeholder}
        {disabled}
        maxlength={maxLength}
        rows="3"
        class="note-textarea"
        onkeydown={handleKeydown}
      ></textarea>
      <div class="edit-footer">
        <span class="char-count">{editValue.length}/{maxLength}</span>
        <div class="edit-actions">
          <button type="button" onclick={cancel} class="btn-cancel">
            Cancel
          </button>
          <button type="button" onclick={save} class="btn-save">
            Save
          </button>
        </div>
      </div>
    </div>
  {:else}
    <button
      type="button"
      onclick={startEdit}
      {disabled}
      class="view-mode"
      class:has-value={!!value}
      class:disabled
    >
      {#if value}
        <p class="note-content">{value}</p>
      {:else}
        <p class="placeholder">{placeholder}</p>
      {/if}
      <span class="edit-hint">Click to edit</span>
    </button>
  {/if}
</div>

<style>
  .note-editor {
    width: 100%;
  }

  .edit-mode {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .note-textarea {
    width: 100%;
    padding: 0.75rem;
    border: 1px solid #3b82f6;
    border-radius: 0.5rem;
    resize: none;
    font-family: inherit;
    font-size: 0.875rem;
    line-height: 1.5;
    box-sizing: border-box;
  }

  .note-textarea:focus {
    outline: none;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
  }

  .edit-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .char-count {
    font-size: 0.75rem;
    color: #6b7280;
  }

  .edit-actions {
    display: flex;
    gap: 0.5rem;
  }

  .btn-cancel,
  .btn-save {
    padding: 0.375rem 0.75rem;
    font-size: 0.813rem;
    font-weight: 500;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .btn-cancel {
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .btn-cancel:hover {
    background: #f9fafb;
  }

  .btn-save {
    background: #3b82f6;
    color: white;
    border: none;
  }

  .btn-save:hover {
    background: #2563eb;
  }

  .view-mode {
    width: 100%;
    padding: 0.75rem;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    background: white;
    text-align: left;
    cursor: pointer;
    transition: all 0.15s ease;
    min-height: 60px;
    display: flex;
    flex-direction: column;
    position: relative;
  }

  .view-mode:hover:not(.disabled) {
    background: #f9fafb;
    border-color: #d1d5db;
  }

  .view-mode.disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }

  .note-content {
    margin: 0;
    font-size: 0.875rem;
    color: #374151;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .placeholder {
    margin: 0;
    font-size: 0.875rem;
    color: #9ca3af;
    font-style: italic;
  }

  .edit-hint {
    position: absolute;
    bottom: 0.5rem;
    right: 0.5rem;
    font-size: 0.688rem;
    color: #9ca3af;
    opacity: 0;
    transition: opacity 0.15s ease;
  }

  .view-mode:hover:not(.disabled) .edit-hint {
    opacity: 1;
  }
</style>
