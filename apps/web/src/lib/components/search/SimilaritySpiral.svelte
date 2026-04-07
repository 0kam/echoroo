<script lang="ts">
  /**
   * SimilaritySpiral - Polar/spiral plot of similarity results over time-of-day.
   *
   * Displays each search result as a dot on a 24-hour clock face,
   * where the angle represents the hour of the recording and the radius/color
   * represents the similarity score.
   *
   * - Angle: hour of day (0h at 12 o'clock, clockwise)
   * - Color: orange (above threshold) vs. muted stone (below threshold)
   * - Radius: scaled by similarity score within the chart area
   */

  import * as m from '$lib/paraglide/messages.js';

  interface Result {
    similarity: number;
    recording_datetime: string | null;
  }

  let {
    results,
    threshold = 0.5,
  }: {
    results: Result[];
    threshold: number;
  } = $props();

  // ============================================================================
  // Layout constants
  // ============================================================================

  const SIZE = 260;
  const cx = SIZE / 2;
  const cy = SIZE / 2;
  const OUTER_R = SIZE / 2 - 28; // Room for hour labels
  const INNER_R = SIZE * 0.08; // Small hole in center
  const MAJOR_HOURS = [0, 3, 6, 9, 12, 15, 18, 21];
  const GRID_HOURS = [0, 6, 12, 18];

  // ============================================================================
  // Geometry helpers (matching PolarHeatmap.svelte patterns)
  // ============================================================================

  /** Convert hour (0-23) to angle in radians. 0h = top, clockwise. */
  function hourToAngle(hour: number): number {
    return (hour / 24) * 2 * Math.PI - Math.PI / 2;
  }

  /** Convert polar coordinates to Cartesian. */
  function polarToCartesian(r: number, angleRad: number): { x: number; y: number } {
    return {
      x: cx + r * Math.cos(angleRad),
      y: cy + r * Math.sin(angleRad),
    };
  }

  // ============================================================================
  // Data processing
  // ============================================================================

  interface PlotDot {
    x: number;
    y: number;
    similarity: number;
    aboveThreshold: boolean;
    hour: number | null;
    label: string;
    key: string;
  }

  const dots = $derived(
    results
      .map((result, i): PlotDot | null => {
        let hour: number | null = null;
        if (result.recording_datetime) {
          try {
            const d = new Date(result.recording_datetime);
            if (!isNaN(d.getTime())) {
              // Use fractional hour for sub-hour precision
              hour = d.getHours() + d.getMinutes() / 60;
            }
          } catch {
            // Ignore invalid dates
          }
        }

        // If no datetime, spread evenly around clock for visibility
        const effectiveHour = hour ?? (i / results.length) * 24;
        const angle = hourToAngle(effectiveHour);

        // Radius: scale similarity (0–1) to (INNER_R+4)–OUTER_R range
        const radius = INNER_R + 4 + result.similarity * (OUTER_R - INNER_R - 4);
        const { x, y } = polarToCartesian(radius, angle);

        const hLabel =
          hour !== null
            ? `${Math.floor(hour).toString().padStart(2, '0')}:${Math.floor((hour % 1) * 60).toString().padStart(2, '0')}`
            : 'unknown time';

        return {
          x,
          y,
          similarity: result.similarity,
          aboveThreshold: result.similarity >= threshold,
          hour,
          label: `${Math.round(result.similarity * 100)}% @ ${hLabel}`,
          key: `${i}-${result.similarity}`,
        };
      })
      .filter((d): d is PlotDot => d !== null),
  );

  const aboveCount = $derived(dots.filter((d) => d.aboveThreshold).length);
  const belowCount = $derived(dots.length - aboveCount);

  // ============================================================================
  // Tooltip
  // ============================================================================

  interface TooltipState {
    visible: boolean;
    x: number;
    y: number;
    label: string;
  }

  let tooltip = $state<TooltipState>({ visible: false, x: 0, y: 0, label: '' });
  let svgEl = $state<SVGSVGElement | null>(null);

  function handleDotEnter(e: MouseEvent, dot: PlotDot) {
    const rect = svgEl?.getBoundingClientRect();
    if (!rect) return;
    tooltip = {
      visible: true,
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      label: dot.label,
    };
  }

  function handleDotLeave() {
    tooltip = { ...tooltip, visible: false };
  }

  function handleMouseMove(e: MouseEvent) {
    if (!tooltip.visible) return;
    const rect = svgEl?.getBoundingClientRect();
    if (!rect) return;
    tooltip = { ...tooltip, x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function formatHour(h: number): string {
    return `${h.toString().padStart(2, '0')}h`;
  }
</script>

<div class="flex flex-col items-center gap-2">
  <!-- Summary badges -->
  <div class="flex gap-3 text-xs">
    <span class="flex items-center gap-1">
      <span class="inline-block h-2 w-2 rounded-full bg-primary-500"></span>
      <span class="font-semibold text-stone-700">{aboveCount}</span>
      <span class="text-stone-500">{m.search_spiral_above()}</span>
    </span>
    <span class="flex items-center gap-1">
      <span class="inline-block h-2 w-2 rounded-full bg-stone-300"></span>
      <span class="font-semibold text-stone-700">{belowCount}</span>
      <span class="text-stone-500">{m.search_spiral_below()}</span>
    </span>
  </div>

  <!-- SVG Polar Chart -->
  <div class="relative" style="width: {SIZE}px; height: {SIZE}px;">
    <svg
      bind:this={svgEl}
      width={SIZE}
      height={SIZE}
      viewBox="0 0 {SIZE} {SIZE}"
      class="overflow-visible"
      role="img"
      aria-label="Similarity results plotted by time of day"
      onmousemove={handleMouseMove}
    >
      <!-- Background circle -->
      <circle
        {cx}
        {cy}
        r={OUTER_R}
        fill="rgb(250,250,249)"
        stroke="rgb(214,211,209)"
        stroke-width="1"
      />

      <!-- Concentric rings at 25%, 50%, 75%, 100% similarity -->
      {#each [0.25, 0.5, 0.75] as ring}
        {@const rr = INNER_R + 4 + ring * (OUTER_R - INNER_R - 4)}
        <circle
          {cx}
          {cy}
          r={rr}
          fill="none"
          stroke="rgb(231,229,228)"
          stroke-width="0.5"
          stroke-dasharray="3 3"
        />
      {/each}

      <!-- Radial grid lines at quarter positions -->
      {#each GRID_HOURS as hour}
        {@const angle = hourToAngle(hour)}
        {@const p1 = polarToCartesian(INNER_R, angle)}
        {@const p2 = polarToCartesian(OUTER_R, angle)}
        <line
          x1={p1.x}
          y1={p1.y}
          x2={p2.x}
          y2={p2.y}
          stroke="rgb(214,211,209)"
          stroke-width="0.5"
        />
      {/each}

      <!-- Dots: below threshold (drawn first, behind) -->
      {#each dots.filter((d) => !d.aboveThreshold) as dot (dot.key + '-below')}
        <circle
          cx={dot.x}
          cy={dot.y}
          r={3}
          fill="rgb(168,162,158)"
          fill-opacity="0.5"
          stroke="none"
          class="cursor-pointer"
          onmouseenter={(e) => handleDotEnter(e, dot)}
          onmouseleave={handleDotLeave}
          role="img"
          aria-label={dot.label}
        />
      {/each}

      <!-- Dots: above threshold (drawn on top) -->
      {#each dots.filter((d) => d.aboveThreshold) as dot (dot.key + '-above')}
        <circle
          cx={dot.x}
          cy={dot.y}
          r={4}
          fill="rgb(255,90,0)"
          fill-opacity="0.75"
          stroke="white"
          stroke-width="0.8"
          class="cursor-pointer"
          onmouseenter={(e) => handleDotEnter(e, dot)}
          onmouseleave={handleDotLeave}
          role="img"
          aria-label={dot.label}
        />
      {/each}

      <!-- Center cover -->
      <circle {cx} {cy} r={INNER_R} fill="white" />

      <!-- Hour labels at major positions -->
      {#each MAJOR_HOURS as hour}
        {@const angle = hourToAngle(hour)}
        {@const pos = polarToCartesian(OUTER_R + 16, angle)}
        <text
          x={pos.x}
          y={pos.y}
          text-anchor="middle"
          dominant-baseline="middle"
          font-size="9"
          fill="rgb(120,113,108)"
          font-family="sans-serif"
        >
          {formatHour(hour)}
        </text>
      {/each}

      <!-- Tick marks -->
      {#each MAJOR_HOURS as hour}
        {@const angle = hourToAngle(hour)}
        {@const t1 = polarToCartesian(OUTER_R + 2, angle)}
        {@const t2 = polarToCartesian(OUTER_R + 6, angle)}
        <line
          x1={t1.x}
          y1={t1.y}
          x2={t2.x}
          y2={t2.y}
          stroke="rgb(156,163,175)"
          stroke-width="1"
        />
      {/each}

      <!-- Similarity ring labels: 50% marker at 3h position -->
      {#each [{ pct: 0.5, label: '50%' }] as ring}
        {@const pos = polarToCartesian(INNER_R + 4 + ring.pct * (OUTER_R - INNER_R - 4), hourToAngle(3))}
        <text
          x={pos.x}
          y={pos.y}
          text-anchor="middle"
          dominant-baseline="middle"
          font-size="8"
          fill="rgb(168,162,158)"
          font-family="sans-serif"
        >{ring.label}</text>
      {/each}
    </svg>

    <!-- Tooltip -->
    {#if tooltip.visible}
      <div
        class="pointer-events-none absolute z-50 rounded-lg bg-stone-900 px-2.5 py-1.5 text-xs text-white shadow-lg"
        style="left: {tooltip.x + 10}px; top: {Math.max(0, tooltip.y - 40)}px;"
        role="tooltip"
      >
        {tooltip.label}
      </div>
    {/if}
  </div>

  <!-- Legend: radius scale explanation -->
  <div class="text-center text-[10px] text-stone-400">
    {m.search_spiral_radius_legend()}
  </div>
</div>
