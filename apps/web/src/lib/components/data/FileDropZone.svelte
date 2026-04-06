<script lang="ts">
  /**
   * FileDropZone - Drag-and-drop file input area for audio file uploads.
   *
   * Handles drag events and file input change. Calls onFilesAdded with selected files.
   * Does not validate files itself — validation is delegated to the parent.
   */

  interface Props {
    isDragOver: boolean;
    onFilesAdded: (files: File[]) => void;
    onDragOver: () => void;
    onDragLeave: () => void;
  }

  let { isDragOver, onFilesAdded, onDragOver, onDragLeave }: Props = $props();

  function handleDragOver(event: DragEvent) {
    event.preventDefault();
    onDragOver();
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    const files = Array.from(event.dataTransfer?.files ?? []);
    onFilesAdded(files);
  }

  function handleFileInputChange(event: Event) {
    const input = event.target as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    onFilesAdded(files);
    // Reset so the same file can be re-selected after removal
    input.value = '';
  }
</script>

<!-- svelte-ignore a11y_interactive_supports_focus -->
<div
  class="mb-4 flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 text-center transition-colors
    {isDragOver
      ? 'border-primary-400 bg-primary-50'
      : 'border-stone-300 hover:border-stone-400 hover:bg-stone-50'}"
  role="button"
  aria-label="Drop audio files here or click to browse"
  ondragover={handleDragOver}
  ondragleave={onDragLeave}
  ondrop={handleDrop}
  onclick={() => document.getElementById('file-drop-zone-input')?.click()}
  onkeydown={(e) => e.key === 'Enter' && document.getElementById('file-drop-zone-input')?.click()}
>
  <svg
    class="mb-3 h-10 w-10 {isDragOver ? 'text-primary-400' : 'text-stone-300'}"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    aria-hidden="true"
  >
    <path
      stroke-linecap="round"
      stroke-linejoin="round"
      stroke-width="1.5"
      d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
    />
  </svg>
  <p class="mb-1 text-sm font-medium text-stone-700">
    {isDragOver ? 'Release to add files' : 'Drag and drop audio files here'}
  </p>
  <p class="text-xs text-stone-400">
    or <span class="text-primary-600 underline">browse</span> &mdash;
    WAV, FLAC, MP3, OGG, OPUS &bull; max 1 GB per file &bull; up to 500 files
  </p>
</div>

<input
  id="file-drop-zone-input"
  type="file"
  multiple
  accept=".wav,.flac,.mp3,.ogg,.opus,audio/*"
  class="hidden"
  onchange={handleFileInputChange}
/>
