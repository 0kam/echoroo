<script lang="ts">
  import type { SpectrogramWindow } from '$lib/types/audio';
  import { getViewportPosition, adjustWindowToBounds, centerWindowOn } from '$lib/utils/viewport';

  interface Props {
    viewport: SpectrogramWindow;
    bounds: SpectrogramWindow;
    onViewportChange?: (viewport: SpectrogramWindow) => void;
    onViewportSave?: () => void;
  }

  let { viewport, bounds, onViewportChange, onViewportSave }: Props = $props();

  let barEl: HTMLDivElement | undefined = $state();
  let barWidth = $state(0);
  let isDragging = $state(false);
  let dragStartX = $state(0);
  let dragStartViewportMin = $state(0);

  // Position of the viewport indicator within the bar
  let indicatorPos = $derived.by(() => {
    if (barWidth <= 0) return { left: 0, width: 0 };
    const pos = getViewportPosition({
      width: barWidth,
      height: 1,
      viewport,
      bounds,
    });
    return { left: pos.left, width: Math.max(pos.width, 8) };
  });

  function getBarX(e: MouseEvent): number {
    if (!barEl) return 0;
    const rect = barEl.getBoundingClientRect();
    return Math.max(0, Math.min(e.clientX - rect.left, barWidth));
  }

  function handleMouseDown(e: MouseEvent) {
    e.preventDefault();
    const x = getBarX(e);
    const timeFrac = x / barWidth;
    const time = bounds.time.min + timeFrac * (bounds.time.max - bounds.time.min);

    // If click is on indicator, start drag; otherwise jump to position
    if (
      x >= indicatorPos.left - 4 &&
      x <= indicatorPos.left + indicatorPos.width + 4
    ) {
      isDragging = true;
      dragStartX = x;
      dragStartViewportMin = viewport.time.min;
      onViewportSave?.();
    } else {
      // Jump viewport center to clicked position
      onViewportSave?.();
      const newVp = adjustWindowToBounds(
        centerWindowOn(viewport, { time }),
        bounds
      );
      onViewportChange?.(newVp);
    }
  }

  function handleMouseMove(e: MouseEvent) {
    if (!isDragging) return;
    const x = getBarX(e);
    const dx = x - dragStartX;
    const timeDelta = (dx / barWidth) * (bounds.time.max - bounds.time.min);
    const newMin = dragStartViewportMin + timeDelta;
    const viewDuration = viewport.time.max - viewport.time.min;
    const clampedMin = Math.max(
      bounds.time.min,
      Math.min(bounds.time.max - viewDuration, newMin)
    );

    onViewportChange?.({
      time: { min: clampedMin, max: clampedMin + viewDuration },
      freq: viewport.freq,
    });
  }

  function handleMouseUp() {
    if (isDragging) {
      isDragging = false;
    }
  }

  function handleMouseLeave() {
    if (isDragging) {
      isDragging = false;
    }
  }

  function handleWheel(e: WheelEvent) {
    e.preventDefault();
    const timeFrac = (viewport.time.max - viewport.time.min) * 0.05;
    const delta = e.deltaY;
    const newVp = adjustWindowToBounds(
      {
        time: {
          min: viewport.time.min + timeFrac * delta * 0.05,
          max: viewport.time.max + timeFrac * delta * 0.05,
        },
        freq: viewport.freq,
      },
      bounds
    );
    onViewportChange?.(newVp);
  }
</script>

<svelte:window
  onmousemove={handleMouseMove}
  onmouseup={handleMouseUp}
/>

<div
  bind:this={barEl}
  bind:clientWidth={barWidth}
  class="relative flex items-center w-full h-8 rounded-md cursor-pointer select-none outline outline-1 outline-stone-300 bg-stone-200 dark:bg-stone-800 dark:outline-stone-700"
  role="scrollbar"
  aria-label="Viewport position"
  aria-valuemin={0}
  aria-valuemax={100}
  aria-valuenow={Math.round(((viewport.time.min - bounds.time.min) / (bounds.time.max - bounds.time.min)) * 100)}
  tabindex="0"
  onmousedown={handleMouseDown}
  onmouseleave={handleMouseLeave}
  onwheel={handleWheel}
>
  <!-- Viewport indicator -->
  <div
    class="absolute h-full rounded-md border border-emerald-500 transition-colors
      {isDragging
        ? 'bg-emerald-500/80 cursor-grabbing'
        : 'bg-emerald-300 dark:bg-emerald-700 hover:bg-emerald-500/80 cursor-grab'}"
    style="left: {indicatorPos.left}px; width: {indicatorPos.width}px;"
  ></div>

  <!-- Time labels -->
  <span class="absolute left-1 top-0.5 text-xs text-stone-400 dark:text-stone-500 pointer-events-none font-mono">
    {bounds.time.min.toFixed(1)}s
  </span>
  <span class="absolute right-1 top-0.5 text-xs text-stone-400 dark:text-stone-500 pointer-events-none font-mono">
    {bounds.time.max.toFixed(1)}s
  </span>
</div>
