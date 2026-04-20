/**
 * Coalescing requestAnimationFrame scheduler for spectrogram redraws.
 *
 * Multiple `request()` calls within the same frame collapse into a single
 * `draw()` invocation on the next animation frame. This matches the behavior
 * previously inlined in SpectrogramViewer.svelte and exists as a standalone
 * utility so future extracted sub-components (canvas / chunk manager /
 * interaction hook) can share a single scheduler per viewer instance.
 *
 * Each call to `createSpectrogramScheduler` returns an isolated instance —
 * no module-level mutable state — so multiple SpectrogramViewer instances on
 * the same page do not interfere with each other.
 */
export interface SpectrogramScheduler {
  /** Request a redraw on the next animation frame. Safe to call repeatedly. */
  request(): void;
  /** Cancel any pending frame without tearing down the scheduler. */
  cancel(): void;
  /** Cancel any pending frame and mark the scheduler as disposed. */
  dispose(): void;
}

export function createSpectrogramScheduler(draw: () => void): SpectrogramScheduler {
  let animFrameId: number | null = null;
  let disposed = false;

  function request(): void {
    if (disposed) return;
    if (animFrameId !== null) return;
    animFrameId = requestAnimationFrame(() => {
      animFrameId = null;
      if (disposed) return;
      draw();
    });
  }

  function cancel(): void {
    if (animFrameId !== null) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
  }

  function dispose(): void {
    cancel();
    disposed = true;
  }

  return { request, cancel, dispose };
}
