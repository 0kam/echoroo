<script lang="ts">
  import { untrack } from 'svelte';
  import type { SpectrogramWindow, InteractionMode } from '$lib/types/audio';
  import type { RecordingDetail } from '$lib/types/data';
  import type { SpectrogramSettings } from '$lib/types/audio';
  import { useChunkManager } from './useChunkManager.svelte';
  import { useSpectrogramInteraction } from './useSpectrogramInteraction.svelte';
  import SpectrogramCanvas from './SpectrogramCanvas.svelte';

  interface Props {
    recording: RecordingDetail;
    projectId: string;
    spectrogramSettings: SpectrogramSettings;
    viewport: SpectrogramWindow;
    bounds: SpectrogramWindow;
    currentTime: number;
    interactionMode: InteractionMode;
    /**
     * When true, all mouse interaction (pan, zoom, seek, crosshair) is disabled.
     * The spectrogram renders identically but the user cannot navigate or seek.
     */
    readonly?: boolean;
    onViewportChange?: (viewport: SpectrogramWindow) => void;
    onViewportSave?: () => void;
    onSeek?: (time: number) => void;
    onModeChange?: (mode: InteractionMode) => void;
  }

  let {
    recording,
    projectId,
    spectrogramSettings,
    viewport,
    bounds,
    currentTime,
    interactionMode,
    readonly = false,
    onViewportChange,
    onViewportSave,
    onSeek,
    onModeChange,
  }: Props = $props();

  // Canvas references. `canvas` is populated once the SpectrogramCanvas child
  // mounts and binds its internal <canvas> element back to the parent via
  // `bind:canvas`. The interaction hook reads `canvas` through its getter.
  let canvas: HTMLCanvasElement | undefined = $state();
  let containerEl: HTMLDivElement | undefined = $state();

  // Canvas dimensions — initial height is taken from settings once; the
  // $effect below keeps `canvasHeight` in sync with spectrogramSettings.height.
  let canvasWidth = $state(0);
  let canvasHeight = $state(untrack(() => spectrogramSettings.height));

  // Spectrogram chunk state is owned by the chunk-manager hook.
  // The hook reactively rebuilds on recording/settings changes and lazy-loads
  // on viewport changes. The child `SpectrogramCanvas` observes `chunkMgr.chunks`
  // through its own $effect to request canvas redraws.
  const chunkMgr = useChunkManager({
    recording: () => recording,
    projectId: () => projectId,
    spectrogramSettings: () => spectrogramSettings,
    viewport: () => viewport,
  });

  // Interaction state (mouse/wheel/keyboard) is owned by the interaction hook.
  // The canvas element lives in SpectrogramCanvas but the parent holds its ref
  // via `bind:canvas` on the child component, so the interaction hook can read
  // it through its getter.
  //
  // Note: `B` (viewport history back) is NOT handled by this hook — the
  // parent route owns the viewport history stack and handles B via its own
  // `svelte:window onkeydown`.
  const interaction = useSpectrogramInteraction({
    canvas: () => canvas,
    containerEl: () => containerEl,
    viewport: () => viewport,
    bounds: () => bounds,
    canvasWidth: () => canvasWidth,
    canvasHeight: () => canvasHeight,
    spectrogramSettings: () => spectrogramSettings,
    interactionMode: () => interactionMode,
    readonly: () => readonly,
    // Wrap callback props so the hook always invokes the current prop value.
    // The hook input is built once at init time; a bare `onViewportChange`
    // would capture the value present at that moment, missing later updates.
    onViewportChange: (vp) => onViewportChange?.(vp),
    onViewportSave: () => onViewportSave?.(),
    onSeek: (time) => onSeek?.(time),
    onModeChange: (mode) => onModeChange?.(mode),
  });

  /**
   * Refresh the auth token and retry all chunks currently in the error state.
   * Thin wrapper preserved for external callers that already use this export.
   */
  export function refreshTokenAndRetryErrors() {
    return chunkMgr.refreshTokenAndRetryErrors();
  }

  // Keep `canvasHeight` in sync with the settings-driven height. The actual
  // canvas element size sync (canvas.width / canvas.height) and redraw
  // scheduling live inside SpectrogramCanvas.
  $effect(() => {
    canvasHeight = spectrogramSettings.height;
  });
</script>

<svelte:window onkeydown={interaction.handleKeyDown} />

<div
  bind:this={containerEl}
  class="spectrogram-container"
  style="height: {spectrogramSettings.height}px;"
  bind:clientWidth={canvasWidth}
>
  <SpectrogramCanvas
    bind:canvas
    {canvasWidth}
    {canvasHeight}
    {viewport}
    {bounds}
    chunks={chunkMgr.chunks}
    chunkImages={chunkMgr.chunkImages}
    {currentTime}
    mousePos={interaction.mousePos}
    zoomBox={interaction.zoomBox}
    {interactionMode}
    {spectrogramSettings}
    {readonly}
    isDragging={interaction.isDragging}
    onmousemove={interaction.handleMouseMove}
    onmousedown={interaction.handleMouseDown}
    onmouseup={interaction.handleMouseUp}
    onmouseleave={interaction.handleMouseLeave}
    ondblclick={interaction.handleDoubleClick}
    onwheel={interaction.handleWheel}
  />

  {#if interaction.mousePos}
    <div class="cursor-info">
      <span>{interaction.mousePos.time.toFixed(3)}s</span>
      <span>{(interaction.mousePos.freq / 1000).toFixed(1)} kHz</span>
    </div>
  {/if}
</div>

<style>
  .spectrogram-container {
    position: relative;
    width: 100%;
    background: #1c1917;
    border-radius: 0.375rem;
    overflow: hidden;
  }

  .cursor-info {
    position: absolute;
    bottom: 0.5rem;
    right: 0.5rem;
    display: flex;
    gap: 0.5rem;
    padding: 0.25rem 0.5rem;
    background: rgba(0, 0, 0, 0.6);
    color: rgba(255, 255, 255, 0.9);
    font-size: 0.75rem;
    font-family: monospace;
    border-radius: 0.25rem;
    pointer-events: none;
  }
</style>
