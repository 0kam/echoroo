<script lang="ts">
  interface Props {
    value?: string;
    placeholder?: string;
    disabled?: boolean;
    maxLength?: number;
    onSave?: (note: string) => void;
    onCancel?: () => void;
  }

  let {
    value = '',
    placeholder = 'Add a note...',
    disabled = false,
    maxLength = 2000,
    onSave,
    onCancel,
  }: Props = $props();

  let isEditing = $state(false);
  let editValue = $state('');

  // Keep editValue in sync when not editing
  $effect(() => {
    if (!isEditing) {
      editValue = value;
    }
  });

  function startEdit() {
    if (disabled) return;
    editValue = value;
    isEditing = true;
  }

  function save() {
    onSave?.(editValue);
    isEditing = false;
  }

  function cancel() {
    editValue = value;
    isEditing = false;
    onCancel?.();
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      cancel();
    } else if (event.key === 'Enter' && event.ctrlKey) {
      save();
    }
  }
</script>

<div class="w-full">
  {#if isEditing}
    <div class="flex flex-col gap-2">
      <textarea
        bind:value={editValue}
        {placeholder}
        {disabled}
        maxlength={maxLength}
        rows="3"
        class="w-full resize-none rounded-lg border border-blue-500 px-3 py-2 font-inherit text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-200"
        onkeydown={handleKeydown}
      ></textarea>
      <div class="flex items-center justify-between">
        <span class="text-xs text-gray-400">{editValue.length}/{maxLength}</span>
        <div class="flex gap-2">
          <button
            type="button"
            onclick={cancel}
            class="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onclick={save}
            class="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700"
          >
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
      class="relative flex min-h-[60px] w-full flex-col rounded-lg border border-gray-200 bg-white p-3 text-left transition-all hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60 {value ? '' : ''}"
    >
      {#if value}
        <p class="m-0 whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-700">{value}</p>
      {:else}
        <p class="m-0 text-sm italic text-gray-400">{placeholder}</p>
      {/if}
      {#if !disabled}
        <span class="absolute bottom-2 right-2 text-[11px] text-gray-300 opacity-0 transition-opacity group-hover:opacity-100">
          Click to edit
        </span>
      {/if}
    </button>
  {/if}
</div>
