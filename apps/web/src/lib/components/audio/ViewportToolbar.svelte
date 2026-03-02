<script lang="ts">
  import type { InteractionMode } from '$lib/types/audio';

  interface Props {
    mode: InteractionMode;
    onReset?: () => void;
    onBack?: () => void;
    onPan?: () => void;
    onZoom?: () => void;
  }

  let { mode, onReset, onBack, onPan, onZoom }: Props = $props();
</script>

<div class="flex items-center gap-1.5">
  <!-- Reset view -->
  <button
    type="button"
    class="toolbar-btn"
    title="Reset to full view"
    onclick={onReset}
  >
    <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  </button>

  <!-- Back view -->
  <button
    type="button"
    class="toolbar-btn"
    title="Previous view (B)"
    onclick={onBack}
  >
    <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M19 12H5M12 19l-7-7 7-7" />
    </svg>
  </button>

  <!-- Pan mode -->
  <button
    type="button"
    class="toolbar-btn {mode === 'panning' ? 'toolbar-btn-active' : ''}"
    title="Pan mode (X)"
    onclick={onPan}
  >
    <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M5 9l-3 3 3 3M9 5l3-3 3 3M15 19l-3 3-3-3M19 9l3 3-3 3M2 12h20M12 2v20" />
    </svg>
    <span class="text-xs ml-0.5">X</span>
  </button>

  <!-- Zoom mode -->
  <button
    type="button"
    class="toolbar-btn {mode === 'zooming' ? 'toolbar-btn-active' : ''}"
    title="Zoom to selection (Z)"
    onclick={onZoom}
  >
    <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="11" cy="11" r="8" />
      <path d="M21 21l-4.35-4.35M11 8v6M8 11h6" />
    </svg>
    <span class="text-xs ml-0.5">Z</span>
  </button>
</div>

<style>
  .toolbar-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.125rem;
    padding: 0.375rem 0.5rem;
    border: 1px solid #d1d5db;
    background: white;
    color: #374151;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    cursor: pointer;
    transition: all 0.15s ease;
    white-space: nowrap;
  }

  :global(.dark) .toolbar-btn {
    background: #3f3f46;
    border-color: #52525b;
    color: #d4d4d8;
  }

  .toolbar-btn:hover {
    background: #f3f4f6;
    border-color: #9ca3af;
  }

  :global(.dark) .toolbar-btn:hover {
    background: #52525b;
  }

  .toolbar-btn:focus-visible {
    outline: 2px solid #10b981;
    outline-offset: 1px;
  }

  .toolbar-btn-active {
    background: #10b981;
    border-color: #059669;
    color: white;
  }

  :global(.dark) .toolbar-btn-active {
    background: #059669;
    border-color: #047857;
    color: white;
  }

  .toolbar-btn-active:hover {
    background: #059669;
    border-color: #047857;
    color: white;
  }
</style>
