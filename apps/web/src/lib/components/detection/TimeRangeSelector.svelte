<script lang="ts">
  /**
   * TimeRangeSelector - Overlay drag handles to adjust detection start/end times.
   *
   * Renders two vertical drag handles on top of a spectrogram.
   * The user drags the handles to adjust the time range of a detection.
   */

  export let duration: number;
  export let initialStart: number;
  export let initialEnd: number;
  export let onChange: (start: number, end: number) => void;

  let containerEl: HTMLDivElement;
  let startTime = initialStart;
  let endTime = initialEnd;

  // Which handle is being dragged: 'start' | 'end' | null
  let dragging: 'start' | 'end' | null = null;

  $: startPercent = duration > 0 ? (startTime / duration) * 100 : 0;
  $: endPercent = duration > 0 ? (endTime / duration) * 100 : 100;

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toFixed(1).padStart(4, '0')}`;
  }

  function getTimeFromClientX(clientX: number): number {
    if (!containerEl) return 0;
    const rect = containerEl.getBoundingClientRect();
    const fraction = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return fraction * duration;
  }

  function handleMouseDown(handle: 'start' | 'end') {
    return (e: MouseEvent) => {
      e.preventDefault();
      dragging = handle;
    };
  }

  function handleMouseMove(e: MouseEvent) {
    if (!dragging) return;
    const t = getTimeFromClientX(e.clientX);

    if (dragging === 'start') {
      startTime = Math.min(t, endTime - 0.1);
      startTime = Math.max(0, startTime);
    } else {
      endTime = Math.max(t, startTime + 0.1);
      endTime = Math.min(duration, endTime);
    }
  }

  function handleMouseUp() {
    if (dragging) {
      dragging = null;
      onChange(startTime, endTime);
    }
  }

  function handleTouchMove(e: TouchEvent) {
    if (!dragging || !e.touches[0]) return;
    e.preventDefault();
    const t = getTimeFromClientX(e.touches[0].clientX);

    if (dragging === 'start') {
      startTime = Math.min(Math.max(0, t), endTime - 0.1);
    } else {
      endTime = Math.max(Math.min(duration, t), startTime + 0.1);
    }
  }

  function handleTouchEnd() {
    if (dragging) {
      dragging = null;
      onChange(startTime, endTime);
    }
  }
</script>

<svelte:window
  on:mousemove={handleMouseMove}
  on:mouseup={handleMouseUp}
  on:touchend={handleTouchEnd}
/>

<div
  bind:this={containerEl}
  class="relative h-full w-full select-none"
  role="group"
  aria-label="Time range selector"
  on:touchmove|passive={handleTouchMove}
>
  <!-- Selection highlight -->
  <div
    class="pointer-events-none absolute inset-y-0 bg-blue-400/15"
    style="left: {startPercent}%; width: {endPercent - startPercent}%;"
  ></div>

  <!-- Start handle -->
  <button
    type="button"
    class="absolute inset-y-0 z-10 flex cursor-ew-resize items-center justify-center"
    style="left: calc({startPercent}% - 8px); width: 16px;"
    aria-label="Start time: {formatTime(startTime)}"
    on:mousedown={handleMouseDown('start')}
    on:touchstart|passive={() => (dragging = 'start')}
  >
    <div class="h-full w-0.5 bg-blue-500 opacity-90"></div>
    <!-- Handle grip indicator -->
    <div class="absolute top-1/2 -translate-y-1/2 rounded bg-blue-500 px-0.5 py-1 text-white shadow-sm">
      <div class="flex flex-col gap-0.5">
        <div class="h-0.5 w-1 bg-white/70"></div>
        <div class="h-0.5 w-1 bg-white/70"></div>
        <div class="h-0.5 w-1 bg-white/70"></div>
      </div>
    </div>
    <!-- Time label -->
    <div class="absolute top-0 left-2 whitespace-nowrap rounded bg-blue-600 px-1 py-0.5 font-mono text-xs text-white shadow-sm">
      {formatTime(startTime)}
    </div>
  </button>

  <!-- End handle -->
  <button
    type="button"
    class="absolute inset-y-0 z-10 flex cursor-ew-resize items-center justify-center"
    style="left: calc({endPercent}% - 8px); width: 16px;"
    aria-label="End time: {formatTime(endTime)}"
    on:mousedown={handleMouseDown('end')}
    on:touchstart|passive={() => (dragging = 'end')}
  >
    <div class="h-full w-0.5 bg-blue-500 opacity-90"></div>
    <!-- Handle grip indicator -->
    <div class="absolute top-1/2 -translate-y-1/2 rounded bg-blue-500 px-0.5 py-1 text-white shadow-sm">
      <div class="flex flex-col gap-0.5">
        <div class="h-0.5 w-1 bg-white/70"></div>
        <div class="h-0.5 w-1 bg-white/70"></div>
        <div class="h-0.5 w-1 bg-white/70"></div>
      </div>
    </div>
    <!-- Time label -->
    <div class="absolute top-0 right-2 whitespace-nowrap rounded bg-blue-600 px-1 py-0.5 font-mono text-xs text-white shadow-sm">
      {formatTime(endTime)}
    </div>
  </button>
</div>
