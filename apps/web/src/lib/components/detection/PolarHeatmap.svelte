<script lang="ts">
  /**
   * PolarHeatmap - SVG-based spiral/polar coordinate heatmap.
   *
   * Displays detection activity by hour (angle) and date (radius).
   * - X-axis (angle): Hours 0-23, with 0h at 12 o'clock, clockwise
   * - Y-axis (radius): Dates, innermost = oldest, outermost = newest
   * - Color: Emerald gradient (light -> deep green) based on detection count
   */

  interface DataPoint {
    date: string;
    hour: number;
    count: number;
  }

  interface TooltipState {
    visible: boolean;
    x: number;
    y: number;
    date: string;
    hour: number;
    count: number;
  }

  export let data: DataPoint[];
  export let scientificName: string;
  export let commonName: string | null;
  export let totalDetections: number;
  export let size: number = 280;

  // ============================================================================
  // Color Scale
  // ============================================================================

  /**
   * Generate emerald color scale from light emerald to deep emerald.
   * Returns RGB string for given intensity (0-1).
   * 0 intensity = near-white, 1 intensity = emerald-600.
   */
  function getEmeraldColor(intensity: number): string {
    if (intensity === 0) {
      return 'rgb(250, 250, 250)';
    }
    const clamped = Math.min(1, Math.max(0, intensity));
    // Power curve for better visual distinction at low values
    const t = Math.pow(clamped, 0.5);
    // emerald-100: rgb(209, 250, 229) -> emerald-600: rgb(5, 150, 105)
    const r = Math.round(209 - t * 204);
    const g = Math.round(250 - t * 100);
    const b = Math.round(229 - t * 124);
    return `rgb(${r}, ${g}, ${b})`;
  }

  /**
   * Generate CSS linear gradient string for the legend.
   */
  function getLegendGradient(): string {
    const stops: string[] = [];
    for (let i = 0; i <= 10; i++) {
      stops.push(`${getEmeraldColor(i / 10)} ${i * 10}%`);
    }
    return `linear-gradient(to right, ${stops.join(', ')})`;
  }

  // ============================================================================
  // Geometry Helpers
  // ============================================================================

  /**
   * Convert hour (0-23) to angle in radians.
   * 0:00 maps to top (12 o'clock), clockwise.
   */
  function hourToAngle(hour: number): number {
    return (hour / 24) * 2 * Math.PI - Math.PI / 2;
  }

  /**
   * Convert polar coordinates to Cartesian.
   */
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

  /**
   * Create SVG arc path string for a wedge/annular segment.
   */
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
      return d.toLocaleDateString('ja-JP', { month: 'short', day: 'numeric' });
    } catch {
      return dateStr;
    }
  }

  // ============================================================================
  // Data Processing (reactive)
  // ============================================================================

  $: dates = (() => {
    if (!data || data.length === 0) return [] as string[];
    const dateSet = new Set(data.map((d) => d.date));
    return Array.from(dateSet).sort(
      (a, b) => new Date(a).getTime() - new Date(b).getTime(),
    );
  })();

  $: maxCount = data && data.length > 0 ? Math.max(...data.map((d) => d.count), 1) : 1;

  $: grid = (() => {
    const m = new Map<string, number>();
    if (data) {
      data.forEach((d) => m.set(`${d.date}-${d.hour}`, d.count));
    }
    return m;
  })();

  // ============================================================================
  // Layout Calculations (reactive)
  // ============================================================================

  $: cx = size / 2;
  $: cy = size / 2;
  $: outerRadius = size / 2 - 30;  // Room for hour labels
  $: innerRadius = Math.max(20, size * 0.09);  // Small hole in center
  $: ringCount = dates.length;
  $: ringWidth = ringCount > 0 ? (outerRadius - innerRadius) / ringCount : 0;
  $: ringGap = 1; // 1px gap between rings

  // Major hour labels (every 3 hours)
  const majorHours = [0, 3, 6, 9, 12, 15, 18, 21];
  // Grid lines at quarter positions
  const gridHours = [0, 6, 12, 18];

  // Precompute wedge paths and colors for rendering
  $: wedges = (() => {
    const result: Array<{
      path: string;
      fill: string;
      date: string;
      hour: number;
      count: number;
      key: string;
    }> = [];

    for (let di = 0; di < dates.length; di++) {
      const date: string = dates[di] ?? '';
      if (!date) continue;
      const ringInner = innerRadius + di * ringWidth;
      const ringOuter = ringInner + ringWidth - ringGap;

      for (let hour = 0; hour < 24; hour++) {
        const count = grid.get(`${date}-${hour}`) ?? 0;
        const intensity = count / maxCount;
        const startAngle = hourToAngle(hour);
        const endAngle = hourToAngle(hour + 1);

        result.push({
          path: createWedgePath(cx, cy, ringInner, ringOuter, startAngle, endAngle),
          fill: getEmeraldColor(intensity),
          date,
          hour,
          count,
          key: `${date}-${hour}`,
        });
      }
    }
    return result;
  })();

  // ============================================================================
  // Tooltip State
  // ============================================================================

  let tooltip: TooltipState = {
    visible: false,
    x: 0,
    y: 0,
    date: '',
    hour: 0,
    count: 0,
  };

  let svgEl: SVGSVGElement | null = null;

  function handleMouseEnter(event: MouseEvent, date: string, hour: number, count: number) {
    const rect = svgEl?.getBoundingClientRect();
    if (!rect) return;
    tooltip = {
      visible: true,
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
      date,
      hour,
      count,
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

<div class="flex flex-col items-center gap-3">
  <!-- Header -->
  <div class="text-center">
    {#if commonName}
      <h3 class="text-sm font-semibold text-stone-900">{commonName}</h3>
      <p class="text-xs italic text-stone-500">{scientificName}</p>
    {:else}
      <h3 class="text-sm font-semibold italic text-stone-900">{scientificName}</h3>
    {/if}
    <p class="mt-0.5 text-xs text-stone-400">
      {totalDetections.toLocaleString()} detections total
    </p>
  </div>

  {#if dates.length === 0}
    <!-- Empty state -->
    <div class="flex flex-col items-center justify-center px-6 py-8 text-center">
      <svg
        class="mx-auto h-10 w-10 text-stone-300"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="1.5"
          d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
        />
      </svg>
      <p class="mt-2 text-sm text-stone-400">No detection data available</p>
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
        aria-label="Polar heatmap of detections by hour and date for {commonName ?? scientificName}"
        on:mousemove={handleMouseMove}
      >
        <!-- Background outline circle -->
        <circle
          cx={cx}
          cy={cy}
          r={outerRadius}
          fill="none"
          stroke="rgb(229, 231, 235)"
          stroke-width="1"
        />

        <!-- Radial grid lines at quarter-hour positions -->
        {#each gridHours as hour}
          {@const angle = hourToAngle(hour)}
          {@const p1 = polarToCartesian(cx, cy, innerRadius, angle)}
          {@const p2 = polarToCartesian(cx, cy, outerRadius, angle)}
          <line
            x1={p1.x}
            y1={p1.y}
            x2={p2.x}
            y2={p2.y}
            stroke="rgb(209, 213, 219)"
            stroke-width="0.5"
          />
        {/each}

        <!-- Data wedge segments -->
        {#each wedges as wedge (wedge.key)}
          <path
            d={wedge.path}
            fill={wedge.fill}
            stroke="white"
            stroke-width="0.3"
            class="cursor-pointer"
            on:mouseenter={(e) => handleMouseEnter(e, wedge.date, wedge.hour, wedge.count)}
            on:mouseleave={handleMouseLeave}
            role="img"
            aria-label="{formatDate(wedge.date)} {formatHour(wedge.hour)}: {wedge.count} detections"
          />
        {/each}

        <!-- Center cover circle -->
        <circle cx={cx} cy={cy} r={innerRadius} fill="white" />

        <!-- Hour labels at major hours -->
        {#each majorHours as hour}
          {@const angle = hourToAngle(hour)}
          {@const pos = polarToCartesian(cx, cy, outerRadius + 16, angle)}
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

        <!-- Hour tick marks -->
        {#each majorHours as hour}
          {@const angle = hourToAngle(hour)}
          {@const tickInner = polarToCartesian(cx, cy, outerRadius + 2, angle)}
          {@const tickOuter = polarToCartesian(cx, cy, outerRadius + 6, angle)}
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
          <div class="mt-1 font-semibold text-emerald-400">
            {tooltip.count}
            {tooltip.count === 1 ? 'detection' : 'detections'}
          </div>
        </div>
      {/if}
    </div>

    <!-- Legend -->
    <div class="flex flex-col items-center gap-1">
      <div class="flex items-center gap-2">
        <span class="text-[10px] text-stone-500">0</span>
        <div
          class="h-3 w-24 rounded-sm"
          style="background: {getLegendGradient()};"
          aria-hidden="true"
        ></div>
        <span class="text-[10px] text-stone-500">{maxCount}</span>
      </div>
      <span class="text-[10px] text-stone-400">Detections per hour</span>
    </div>

    <!-- Date range indicator -->
    {#if dates.length > 1}
      {@const firstDate = dates[0] ?? ''}
      {@const lastDate = dates[dates.length - 1] ?? ''}
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
