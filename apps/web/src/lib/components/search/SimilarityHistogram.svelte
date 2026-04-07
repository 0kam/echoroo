<script lang="ts">
  /**
   * SimilarityHistogram - SVG-based histogram of similarity score distribution.
   *
   * Displays how many search results fall into each 5%-wide similarity bin,
   * with a draggable threshold line to filter results interactively.
   *
   * - X-axis: similarity percentage (0–100%), 5% bins
   * - Y-axis: count of results in each bin
   * - Draggable red threshold line
   * - Count summary above/below threshold
   */

  import * as m from '$lib/paraglide/messages.js';

  interface Result {
    similarity: number;
  }

  let {
    results,
    threshold = $bindable(),
    onThresholdChange,
  }: {
    results: Result[];
    threshold: number;
    onThresholdChange: (value: number) => void;
  } = $props();

  // ============================================================================
  // Layout constants
  // ============================================================================

  const WIDTH = 320;
  const HEIGHT = 140;
  const MARGIN = { top: 12, right: 12, bottom: 28, left: 36 };
  const CHART_W = WIDTH - MARGIN.left - MARGIN.right;
  const CHART_H = HEIGHT - MARGIN.top - MARGIN.bottom;
  const NUM_BINS = 20; // 5% intervals

  // ============================================================================
  // Data processing
  // ============================================================================

  /** Build histogram bins (each bin covers 5% similarity range). */
  const bins = $derived((() => {
    const counts = new Array<number>(NUM_BINS).fill(0);
    for (const r of results) {
      const idx = Math.min(Math.floor(r.similarity * NUM_BINS), NUM_BINS - 1);
      const safeIdx = idx >= 0 && idx < NUM_BINS ? idx : 0;
      counts[safeIdx] = (counts[safeIdx] ?? 0) + 1;
    }
    return counts;
  })());

  const maxCount = $derived(Math.max(...bins, 1));

  /** Bar geometry for each bin. */
  const bars = $derived(
    bins.map((count, i) => {
      const x = (i / NUM_BINS) * CHART_W;
      const w = CHART_W / NUM_BINS - 1;
      const barH = (count / maxCount) * CHART_H;
      const y = CHART_H - barH;
      // Color: lighter orange for low similarity, richer orange for high
      const t = i / (NUM_BINS - 1);
      const alpha = 0.3 + t * 0.7;
      return { x, y, w, h: barH, count, alpha, binStart: i / NUM_BINS };
    }),
  );

  // ============================================================================
  // Threshold derived values
  // ============================================================================

  const thresholdX = $derived(threshold * CHART_W);
  const countAbove = $derived(results.filter((r) => r.similarity >= threshold).length);
  const countBelow = $derived(results.length - countAbove);

  // ============================================================================
  // X-axis labels (every 20%)
  // ============================================================================

  const xLabels = [0, 0.2, 0.4, 0.6, 0.8, 1.0];

  // ============================================================================
  // Dragging logic
  // ============================================================================

  let svgEl = $state<SVGSVGElement | null>(null);
  let isDragging = $state(false);

  function getThresholdFromMouseX(clientX: number): number {
    const rect = svgEl?.getBoundingClientRect();
    if (!rect) return threshold;
    const relX = clientX - rect.left - MARGIN.left;
    const clamped = Math.max(0, Math.min(CHART_W, relX));
    return Math.round((clamped / CHART_W) * 20) / 20; // Snap to 5% grid
  }

  function handleMouseDown(e: MouseEvent) {
    isDragging = true;
    e.preventDefault();
  }

  function handleMouseMove(e: MouseEvent) {
    if (!isDragging) return;
    const newThreshold = getThresholdFromMouseX(e.clientX);
    threshold = newThreshold;
    onThresholdChange(newThreshold);
  }

  function handleMouseUp() {
    isDragging = false;
  }

  function handleSvgClick(e: MouseEvent) {
    if (isDragging) return;
    const newThreshold = getThresholdFromMouseX(e.clientX);
    threshold = newThreshold;
    onThresholdChange(newThreshold);
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
  <!-- Count summary above/below threshold -->
  <div class="flex items-center justify-between px-1 text-xs text-stone-500">
    <span>
      <span class="font-semibold text-stone-700">{countAbove.toLocaleString()}</span>
      {m.search_histogram_above({ threshold: formatPct(threshold) })}
    </span>
    <span class="text-stone-400">{countBelow.toLocaleString()} {m.search_histogram_below()}</span>
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
    aria-label="Similarity score distribution histogram"
    onclick={handleSvgClick}
  >
    <g transform="translate({MARGIN.left},{MARGIN.top})">
      <!-- Y-axis baseline -->
      <line
        x1={0}
        y1={CHART_H}
        x2={CHART_W}
        y2={CHART_H}
        stroke="rgb(214,211,209)"
        stroke-width="1"
      />

      <!-- Bars -->
      {#each bars as bar, i (i)}
        <rect
          x={bar.x}
          y={bar.y}
          width={bar.w}
          height={bar.h}
          fill="rgb(255,90,0)"
          fill-opacity={bar.binStart >= threshold ? bar.alpha : bar.alpha * 0.3}
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
          fill="rgb(120,113,108)"
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
        fill="rgb(120,113,108)"
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
        fill="rgb(120,113,108)"
        font-family="sans-serif"
      >
        0
      </text>

      <!-- Threshold line (draggable) -->
      <!-- Invisible wide hit area for easier dragging -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <line
        x1={thresholdX}
        y1={-4}
        x2={thresholdX}
        y2={CHART_H + 4}
        stroke="transparent"
        stroke-width="12"
        class="cursor-ew-resize"
        onmousedown={handleMouseDown}
      />
      <!-- Visible red threshold line -->
      <line
        x1={thresholdX}
        y1={-4}
        x2={thresholdX}
        y2={CHART_H + 4}
        stroke="rgb(220,38,38)"
        stroke-width="2"
        stroke-dasharray="3 2"
        pointer-events="none"
      />
      <!-- Threshold handle circle -->
      <circle
        cx={thresholdX}
        cy={CHART_H / 2}
        r={6}
        fill="rgb(220,38,38)"
        stroke="white"
        stroke-width="2"
        class="cursor-ew-resize"
        pointer-events="all"
        onmousedown={handleMouseDown}
        role="slider"
        tabindex="0"
        aria-label="Threshold: {formatPct(threshold)}"
        aria-valuenow={Math.round(threshold * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      />
      <!-- Threshold label above line -->
      <text
        x={thresholdX}
        y={-6}
        text-anchor={thresholdX > CHART_W * 0.8 ? 'end' : 'middle'}
        font-size="9"
        font-weight="600"
        fill="rgb(220,38,38)"
        font-family="sans-serif"
        pointer-events="none"
      >
        {formatPct(threshold)}
      </text>
    </g>
  </svg>
</div>
