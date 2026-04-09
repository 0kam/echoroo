<script lang="ts">
  /**
   * SimilarityHistogram - SVG-based histogram of similarity score distribution.
   *
   * Displays how many search results fall into each similarity bin,
   * with two draggable threshold lines to define a min/max range.
   *
   * - X-axis: similarity percentage (0–100%)
   * - Y-axis: count of results in each bin
   * - Two draggable red lines: min (left edge) and max (right edge) of the active range
   * - Bars within the range are fully opaque; bars outside are dimmed
   * - Count summary shows results within the range
   *
   * Accepts pre-computed bins from the server-side distribution API
   * instead of binning individual results client-side.
   */

  import * as m from '$lib/paraglide/messages.js';
  import type { DistributionBin } from '$lib/types/search';

  let {
    bins,
    thresholdMin = $bindable(),
    thresholdMax = $bindable(),
    onThresholdMinChange,
    onThresholdMaxChange,
  }: {
    bins: DistributionBin[];
    thresholdMin: number;
    thresholdMax: number;
    onThresholdMinChange: (value: number) => void;
    onThresholdMaxChange: (value: number) => void;
  } = $props();

  // ============================================================================
  // Layout constants
  // ============================================================================

  const WIDTH = 320;
  const HEIGHT = 140;
  const MARGIN = { top: 12, right: 12, bottom: 28, left: 36 };
  const CHART_W = WIDTH - MARGIN.left - MARGIN.right;
  const CHART_H = HEIGHT - MARGIN.top - MARGIN.bottom;

  // ============================================================================
  // Data processing
  // ============================================================================

  const maxCount = $derived(Math.max(...bins.map((b) => b.count), 1));

  const totalCount = $derived(bins.reduce((sum, b) => sum + b.count, 0));

  /** Bar geometry for each bin. */
  const bars = $derived(
    bins.map((bin) => {
      const x = bin.lower * CHART_W;
      const w = Math.max(1, (bin.upper - bin.lower) * CHART_W - 1);
      const barH = (bin.count / maxCount) * CHART_H;
      const y = CHART_H - barH;
      // Color: lighter orange for low similarity, richer orange for high
      const midpoint = (bin.lower + bin.upper) / 2;
      const alpha = 0.3 + midpoint * 0.7;
      const inRange = bin.lower >= thresholdMin && bin.upper <= thresholdMax + 0.001;
      return { x, y, w, h: barH, count: bin.count, alpha, binStart: bin.lower, inRange };
    }),
  );

  // ============================================================================
  // Range derived values
  // ============================================================================

  const minX = $derived(thresholdMin * CHART_W);
  const maxX = $derived(thresholdMax * CHART_W);

  const countInRange = $derived(
    bins
      .filter((b) => b.lower >= thresholdMin && b.upper <= thresholdMax + 0.001)
      .reduce((sum, b) => sum + b.count, 0)
  );

  const countOutOfRange = $derived(totalCount - countInRange);

  // ============================================================================
  // X-axis labels (every 20%)
  // ============================================================================

  const xLabels = [0, 0.2, 0.4, 0.6, 0.8, 1.0];

  // ============================================================================
  // Dragging logic — tracks which handle is being dragged
  // ============================================================================

  let svgEl = $state<SVGSVGElement | null>(null);
  /** Which handle is currently being dragged: 'min', 'max', or null */
  let dragging = $state<'min' | 'max' | null>(null);

  function getValueFromMouseX(clientX: number): number {
    const rect = svgEl?.getBoundingClientRect();
    if (!rect) return 0;
    const relX = clientX - rect.left - MARGIN.left;
    const clamped = Math.max(0, Math.min(CHART_W, relX));
    return Math.round((clamped / CHART_W) * 20) / 20; // Snap to 5% grid
  }

  function handleMinMouseDown(e: MouseEvent) {
    dragging = 'min';
    e.preventDefault();
    e.stopPropagation();
  }

  function handleMaxMouseDown(e: MouseEvent) {
    dragging = 'max';
    e.preventDefault();
    e.stopPropagation();
  }

  function handleMouseMove(e: MouseEvent) {
    if (!dragging) return;
    const val = getValueFromMouseX(e.clientX);
    if (dragging === 'min') {
      // Min cannot exceed max; clamp to [0, thresholdMax - 0.05]
      const newMin = Math.min(val, thresholdMax - 0.05);
      thresholdMin = newMin;
      onThresholdMinChange(newMin);
    } else {
      // Max cannot go below min; clamp to [thresholdMin + 0.05, 1]
      const newMax = Math.max(val, thresholdMin + 0.05);
      thresholdMax = newMax;
      onThresholdMaxChange(newMax);
    }
  }

  function handleMouseUp() {
    dragging = null;
  }

  /**
   * Click on the chart background: move the nearest handle to the clicked position.
   */
  function handleSvgClick(e: MouseEvent) {
    if (dragging) return;
    const val = getValueFromMouseX(e.clientX);
    const distToMin = Math.abs(val - thresholdMin);
    const distToMax = Math.abs(val - thresholdMax);
    if (distToMin <= distToMax) {
      const newMin = Math.min(val, thresholdMax - 0.05);
      thresholdMin = newMin;
      onThresholdMinChange(newMin);
    } else {
      const newMax = Math.max(val, thresholdMin + 0.05);
      thresholdMax = newMax;
      onThresholdMaxChange(newMax);
    }
  }

  // ============================================================================
  // Helpers
  // ============================================================================

  function formatPct(v: number): string {
    return `${Math.round(v * 100)}%`;
  }
</script>

<svelte:window onmousemove={handleMouseMove} onmouseup={handleMouseUp} />

<div class="flex flex-col gap-1.5">
  <!-- Count summary: in range vs out of range -->
  <div class="flex items-center justify-between px-1 text-xs text-stone-500">
    <span>
      <span class="font-semibold text-stone-700">{countInRange.toLocaleString()}</span>
      {m.search_histogram_in_range({ min: formatPct(thresholdMin), max: formatPct(thresholdMax) })}
    </span>
    <span class="text-stone-400">{countOutOfRange.toLocaleString()} {m.search_histogram_outside()}</span>
  </div>

  <!-- SVG Histogram -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <svg
    bind:this={svgEl}
    width={WIDTH}
    height={HEIGHT}
    viewBox="0 0 {WIDTH} {HEIGHT}"
    class="w-full cursor-crosshair select-none overflow-visible"
    style="max-width: {WIDTH}px;"
    role="img"
    aria-label={m.search_aria_histogram()}
    onclick={handleSvgClick}
  >
    <g transform="translate({MARGIN.left},{MARGIN.top})">
      <!-- Y-axis baseline -->
      <line
        x1={0}
        y1={CHART_H}
        x2={CHART_W}
        y2={CHART_H}
        stroke="rgb(var(--stone-300))"
        stroke-width="1"
      />

      <!-- Shaded range background -->
      <rect
        x={minX}
        y={0}
        width={Math.max(0, maxX - minX)}
        height={CHART_H}
        fill="rgb(var(--primary-500))"
        fill-opacity="0.07"
        pointer-events="none"
      />

      <!-- Bars -->
      {#each bars as bar, i (i)}
        <rect
          x={bar.x}
          y={bar.y}
          width={bar.w}
          height={bar.h}
          fill="rgb(var(--primary-500))"
          fill-opacity={bar.inRange ? bar.alpha : bar.alpha * 0.25}
          rx="1"
        />
      {/each}

      <!-- X-axis labels -->
      {#each xLabels as label}
        {@const lx = label * CHART_W}
        <text
          x={lx}
          y={CHART_H + 14}
          text-anchor="middle"
          font-size="9"
          fill="rgb(var(--stone-500))"
          font-family="sans-serif"
        >
          {formatPct(label)}
        </text>
      {/each}

      <!-- Y-axis: max count label -->
      <text
        x={-4}
        y={0}
        text-anchor="end"
        dominant-baseline="hanging"
        font-size="9"
        fill="rgb(var(--stone-500))"
        font-family="sans-serif"
      >
        {maxCount}
      </text>
      <text
        x={-4}
        y={CHART_H}
        text-anchor="end"
        dominant-baseline="auto"
        font-size="9"
        fill="rgb(var(--stone-500))"
        font-family="sans-serif"
      >
        0
      </text>

      <!-- ── Min threshold line ── -->
      <!-- Invisible wide hit area for easier dragging -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <line
        x1={minX}
        y1={-4}
        x2={minX}
        y2={CHART_H + 4}
        stroke="transparent"
        stroke-width="12"
        class="cursor-ew-resize"
        onmousedown={handleMinMouseDown}
      />
      <!-- Visible min line -->
      <line
        x1={minX}
        y1={-4}
        x2={minX}
        y2={CHART_H + 4}
        stroke="rgb(var(--color-danger))"
        stroke-width="2"
        stroke-dasharray="3 2"
        pointer-events="none"
      />
      <!-- Min handle circle -->
      <circle
        cx={minX}
        cy={CHART_H / 2}
        r={6}
        fill="rgb(var(--color-danger))"
        stroke="white"
        stroke-width="2"
        class="cursor-ew-resize"
        pointer-events="all"
        onmousedown={handleMinMouseDown}
        role="slider"
        tabindex="0"
        aria-label={m.search_aria_threshold_min({ value: formatPct(thresholdMin) })}
        aria-valuenow={Math.round(thresholdMin * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      />
      <!-- Min label above line -->
      <text
        x={minX}
        y={-6}
        text-anchor={minX < CHART_W * 0.15 ? 'start' : 'middle'}
        font-size="9"
        font-weight="600"
        fill="rgb(var(--color-danger))"
        font-family="sans-serif"
        pointer-events="none"
      >
        {formatPct(thresholdMin)}
      </text>

      <!-- ── Max threshold line ── -->
      <!-- Invisible wide hit area for easier dragging -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <line
        x1={maxX}
        y1={-4}
        x2={maxX}
        y2={CHART_H + 4}
        stroke="transparent"
        stroke-width="12"
        class="cursor-ew-resize"
        onmousedown={handleMaxMouseDown}
      />
      <!-- Visible max line -->
      <line
        x1={maxX}
        y1={-4}
        x2={maxX}
        y2={CHART_H + 4}
        stroke="rgb(var(--color-danger))"
        stroke-width="2"
        stroke-dasharray="3 2"
        pointer-events="none"
      />
      <!-- Max handle circle -->
      <circle
        cx={maxX}
        cy={CHART_H / 2}
        r={6}
        fill="rgb(var(--color-danger))"
        stroke="white"
        stroke-width="2"
        class="cursor-ew-resize"
        pointer-events="all"
        onmousedown={handleMaxMouseDown}
        role="slider"
        tabindex="0"
        aria-label={m.search_aria_threshold_max({ value: formatPct(thresholdMax) })}
        aria-valuenow={Math.round(thresholdMax * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      />
      <!-- Max label above line -->
      <text
        x={maxX}
        y={-6}
        text-anchor={maxX > CHART_W * 0.85 ? 'end' : 'middle'}
        font-size="9"
        font-weight="600"
        fill="rgb(var(--color-danger))"
        font-family="sans-serif"
        pointer-events="none"
      >
        {formatPct(thresholdMax)}
      </text>
    </g>
  </svg>
</div>
