<script lang="ts">
  /**
   * SearchTimeHeatmap - Polar heatmap of average similarity by hour and date.
   *
   * Reuses the same visual style as the detection PolarHeatmap:
   * - Angle: Hours 0-23, with 0h at 12 o'clock, clockwise
   * - Radius: Dates, innermost = oldest, outermost = newest
   * - Color: Orange gradient based on average similarity per (date, hour) cell
   *
   * Accepts pre-computed cells from the time-distribution API endpoint.
   * Each cell contains a date, hour, avg_similarity, and count.
   */

  import { getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { TimeDistributionCell } from '$lib/types/search';

  let {
    cells = [],
    size = 260,
    timezone = 'UTC',
  }: {
    cells: TimeDistributionCell[];
    size?: number;
    timezone?: string;
  } = $props();

  // ============================================================================
  // Color Scale (viridis-inspired multi-hue palette for maximum contrast)
  // ============================================================================

  // Viridis-inspired stops with brand orange (#FF5A00) at the high end
  const COLOR_STOPS: Array<{ r: number; g: number; b: number }> = [
    { r: 68, g: 1, b: 84 },   // t=0.00: dark purple
    { r: 49, g: 104, b: 142 }, // t=0.25: blue
    { r: 53, g: 183, b: 121 }, // t=0.50: green
    { r: 253, g: 231, b: 37 }, // t=0.75: yellow
    { r: 255, g: 90, b: 0 },   // t=1.00: brand orange (high similarity)
  ];

  /** Interpolate along the multi-stop color palette. t in [0, 1]. */
  function interpolateColor(t: number): string {
    const n = COLOR_STOPS.length - 1;
    const scaledT = Math.min(1, Math.max(0, t)) * n;
    const i = Math.min(n - 1, Math.floor(scaledT));
    const frac = scaledT - i;
    const c0 = COLOR_STOPS[i]!;
    const c1 = COLOR_STOPS[i + 1]!;
    const r = Math.round(c0.r + frac * (c1.r - c0.r));
    const g = Math.round(c0.g + frac * (c1.g - c0.g));
    const b = Math.round(c0.b + frac * (c1.b - c0.b));
    return `rgb(${r}, ${g}, ${b})`;
  }

  /** Color for a cell using the actual data range for normalization. */
  function getColor(t: number, hasData: boolean): string {
    if (!hasData) {
      // No-data cells: clearly distinct light gray
      return 'rgb(226, 224, 222)';
    }
    return interpolateColor(t);
  }

  function getLegendGradient(): string {
    const stops: string[] = [];
    for (let i = 0; i <= 20; i++) {
      stops.push(`${interpolateColor(i / 20)} ${i * 5}%`);
    }
    return `linear-gradient(to right, ${stops.join(', ')})`;
  }

  // ============================================================================
  // Geometry Helpers
  // ============================================================================

  function hourToAngle(hour: number): number {
    return (hour / 24) * 2 * Math.PI - Math.PI / 2;
  }

  function polarToCartesian(
    cx: number,
    cy: number,
    radius: number,
    angleRad: number,
  ): { x: number; y: number } {
    return {
      x: cx + radius * Math.cos(angleRad),
      y: cy + radius * Math.sin(angleRad),
    };
  }

  function createWedgePath(
    cx: number,
    cy: number,
    innerR: number,
    outerR: number,
    startAngle: number,
    endAngle: number,
  ): string {
    const i1 = polarToCartesian(cx, cy, innerR, startAngle);
    const i2 = polarToCartesian(cx, cy, innerR, endAngle);
    const o1 = polarToCartesian(cx, cy, outerR, startAngle);
    const o2 = polarToCartesian(cx, cy, outerR, endAngle);
    const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;

    return [
      `M ${i1.x} ${i1.y}`,
      `A ${innerR} ${innerR} 0 ${largeArc} 1 ${i2.x} ${i2.y}`,
      `L ${o2.x} ${o2.y}`,
      `A ${outerR} ${outerR} 0 ${largeArc} 0 ${o1.x} ${o1.y}`,
      'Z',
    ].join(' ');
  }

  // ============================================================================
  // Format Helpers
  // ============================================================================

  function formatHour(hour: number): string {
    return `${hour.toString().padStart(2, '0')}:00`;
  }

  function formatDate(dateStr: string): string {
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString(getLocale(), { month: 'short', day: 'numeric' });
    } catch {
      return dateStr;
    }
  }

  // ============================================================================
  // Data Processing
  // ============================================================================

  /** Build a grid from pre-computed API cells keyed by "date-hour" */
  const binned = $derived((() => {
    const grid = new Map<string, number>();
    const dateSet = new Set<string>();

    for (const cell of cells) {
      const key = `${cell.date}-${cell.hour}`;
      grid.set(key, cell.avg_similarity);
      dateSet.add(cell.date);
    }

    const dates = Array.from(dateSet).sort(
      (a, b) => new Date(a).getTime() - new Date(b).getTime(),
    );

    return { grid, dates };
  })());

  /** Min/max average similarity across all cells (used for data-range color normalization) */
  const dataRange = $derived((() => {
    let min = Infinity;
    let max = -Infinity;
    for (const v of binned.grid.values()) {
      if (v < min) min = v;
      if (v > max) max = v;
    }
    if (!isFinite(min) || !isFinite(max)) return { min: 0, max: 1, range: 1 };
    // Avoid division by zero when all values are identical
    const range = max - min;
    return { min, max, range: range > 0 ? range : 1 };
  })());

  // ============================================================================
  // Layout
  // ============================================================================

  const cxVal = $derived(size / 2);
  const cyVal = $derived(size / 2);
  const outerRadius = $derived(size / 2 - 28);
  const innerRadius = $derived(Math.max(18, size * 0.08));
  const ringCount = $derived(binned.dates.length);
  const ringWidth = $derived(ringCount > 0 ? (outerRadius - innerRadius) / ringCount : 0);
  const ringGap = 1;
  const majorHours = [0, 3, 6, 9, 12, 15, 18, 21];
  const gridHours = [0, 6, 12, 18];

  // Precompute wedges
  const wedges = $derived((() => {
    const result: Array<{
      path: string;
      fill: string;
      date: string;
      hour: number;
      avg: number;
      key: string;
    }> = [];

    for (let di = 0; di < binned.dates.length; di++) {
      const date = binned.dates[di] ?? '';
      if (!date) continue;
      const rInner = innerRadius + di * ringWidth;
      const rOuter = rInner + ringWidth - ringGap;

      for (let hour = 0; hour < 24; hour++) {
        const rawAvg = binned.grid.get(`${date}-${hour}`);
        const hasData = rawAvg !== undefined;
        const avg = rawAvg ?? 0;
        // Normalize to [0, 1] using the actual data range for maximum contrast
        const t = hasData ? (avg - dataRange.min) / dataRange.range : 0;
        const startAngle = hourToAngle(hour);
        const endAngle = hourToAngle(hour + 1);

        result.push({
          path: createWedgePath(cxVal, cyVal, rInner, rOuter, startAngle, endAngle),
          fill: getColor(t, hasData),
          date,
          hour,
          avg,
          key: `${date}-${hour}`,
        });
      }
    }
    return result;
  })());

  // ============================================================================
  // Tooltip
  // ============================================================================

  interface TooltipState {
    visible: boolean;
    x: number;
    y: number;
    date: string;
    hour: number;
    avg: number;
  }

  let tooltip: TooltipState = $state({
    visible: false,
    x: 0,
    y: 0,
    date: '',
    hour: 0,
    avg: 0,
  });

  let svgEl: SVGSVGElement | null = $state(null);

  function handleMouseEnter(event: MouseEvent, date: string, hour: number, avg: number) {
    const rect = svgEl?.getBoundingClientRect();
    if (!rect) return;
    tooltip = {
      visible: true,
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
      date,
      hour,
      avg,
    };
  }

  function handleMouseLeave() {
    tooltip = { ...tooltip, visible: false };
  }

  function handleMouseMove(event: MouseEvent) {
    if (!tooltip.visible) return;
    const rect = svgEl?.getBoundingClientRect();
    if (!rect) return;
    tooltip = {
      ...tooltip,
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }
</script>

<div class="flex flex-col items-center gap-2">
  {#if binned.dates.length === 0}
    <!-- Empty state: no datetime data available -->
    <div class="flex flex-col items-center justify-center px-6 py-6 text-center">
      <svg
        class="mx-auto h-8 w-8 text-stone-300"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="1.5"
          d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
        />
      </svg>
      <p class="mt-2 text-xs text-stone-400">
        {m.search_time_no_datetime()}
      </p>
    </div>
  {:else}
    <!-- SVG Chart -->
    <div class="relative" style="width: {size}px; height: {size}px;">
      <svg
        bind:this={svgEl}
        width={size}
        height={size}
        class="overflow-visible"
        role="img"
        aria-label={m.search_time_distribution()}
        onmousemove={handleMouseMove}
      >
        <!-- Background outline circle -->
        <circle
          cx={cxVal}
          cy={cyVal}
          r={outerRadius}
          fill="none"
          stroke="rgb(229, 231, 235)"
          stroke-width="1"
        />

        <!-- Radial grid lines -->
        {#each gridHours as hour}
          {@const angle = hourToAngle(hour)}
          {@const p1 = polarToCartesian(cxVal, cyVal, innerRadius, angle)}
          {@const p2 = polarToCartesian(cxVal, cyVal, outerRadius, angle)}
          <line
            x1={p1.x}
            y1={p1.y}
            x2={p2.x}
            y2={p2.y}
            stroke="rgb(209, 213, 219)"
            stroke-width="0.5"
          />
        {/each}

        <!-- Wedge segments -->
        {#each wedges as wedge (wedge.key)}
          <path
            d={wedge.path}
            fill={wedge.fill}
            stroke="white"
            stroke-width="0.3"
            class="cursor-pointer"
            onmouseenter={(e) => handleMouseEnter(e, wedge.date, wedge.hour, wedge.avg)}
            onmouseleave={handleMouseLeave}
            role="img"
            aria-label="{formatDate(wedge.date)} {formatHour(wedge.hour)}: {wedge.avg > 0 ? Math.round(wedge.avg * 100) + '%' : 'no data'}"
          />
        {/each}

        <!-- Center cover -->
        <circle cx={cxVal} cy={cyVal} r={innerRadius} fill="white" />

        <!-- Hour labels -->
        {#each majorHours as hour}
          {@const angle = hourToAngle(hour)}
          {@const pos = polarToCartesian(cxVal, cyVal, outerRadius + 16, angle)}
          <text
            x={pos.x}
            y={pos.y}
            text-anchor="middle"
            dominant-baseline="middle"
            font-size="9"
            fill="rgb(120, 113, 108)"
            font-family="sans-serif"
          >
            {hour === 0 ? '0h' : `${hour}h`}
          </text>
        {/each}

        <!-- Tick marks -->
        {#each majorHours as hour}
          {@const angle = hourToAngle(hour)}
          {@const tickInner = polarToCartesian(cxVal, cyVal, outerRadius + 2, angle)}
          {@const tickOuter = polarToCartesian(cxVal, cyVal, outerRadius + 6, angle)}
          <line
            x1={tickInner.x}
            y1={tickInner.y}
            x2={tickOuter.x}
            y2={tickOuter.y}
            stroke="rgb(156, 163, 175)"
            stroke-width="1"
          />
        {/each}
      </svg>

      <!-- Tooltip -->
      {#if tooltip.visible}
        <div
          class="pointer-events-none absolute z-50 rounded-lg bg-stone-900 px-3 py-2 text-xs text-white shadow-lg"
          style="left: {tooltip.x + 10}px; top: {Math.max(0, tooltip.y - 50)}px;"
          role="tooltip"
        >
          <div class="font-medium">{formatDate(tooltip.date)}</div>
          <div class="text-stone-300">
            {formatHour(tooltip.hour)} - {formatHour((tooltip.hour + 1) % 24)}
          </div>
          <div class="mt-1 font-semibold text-primary-400">
            {tooltip.avg > 0 ? Math.round(tooltip.avg * 100) + '%' : '—'}
          </div>
        </div>
      {/if}
    </div>

    <!-- Legend -->
    <div class="flex flex-col items-center gap-1">
      <div class="flex items-center gap-2">
        <span class="text-[10px] text-stone-500">{Math.round(dataRange.min * 100)}%</span>
        <div
          class="h-3 w-24 rounded-sm"
          style="background: {getLegendGradient()};"
          aria-hidden="true"
        ></div>
        <span class="text-[10px] text-stone-500">{Math.round(dataRange.max * 100)}%</span>
      </div>
      <!-- No-data swatch -->
      <div class="flex items-center gap-1">
        <div class="h-3 w-3 rounded-sm" style="background: rgb(226, 224, 222);" aria-hidden="true"></div>
        <span class="text-[10px] text-stone-400">{m.search_time_no_data()}</span>
      </div>
      <span class="text-[10px] text-stone-400">{m.search_time_avg_similarity_per_hour()}</span>
      {#if timezone}
        <span class="text-[10px] text-stone-400">({timezone})</span>
      {/if}
    </div>

    <!-- Date range indicator -->
    {#if binned.dates.length > 1}
      {@const firstDate = binned.dates[0] ?? ''}
      {@const lastDate = binned.dates[binned.dates.length - 1] ?? ''}
      <div class="text-center text-[10px] text-stone-400">
        <span class="font-medium">Center:</span>
        {formatDate(firstDate)}
        <span class="mx-1 text-stone-300">|</span>
        <span class="font-medium">Edge:</span>
        {formatDate(lastDate)}
      </div>
    {/if}
  {/if}
</div>
