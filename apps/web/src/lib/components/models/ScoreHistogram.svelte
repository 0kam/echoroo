<script lang="ts">
  /**
   * ScoreHistogram - Visualises a 20-bin distribution of sigmoid-probability
   * predictions produced by the active-learning scorer.
   *
   * Dependency-free implementation: renders the bars as plain absolutely
   * positioned divs inside a fixed-height chart area, so there is no need
   * for a charting library.
   *
   * Typical layout:
   *
   *   Score distribution                           mean 0.15
   *   |▁▁▂▃▅▇█▅▃▂▁                             |
   *   |<------- dashed mean marker ------->    |
   *   0.0               0.5               1.0
   *   mean: 0.15 | pos (>=0.5): 234 | neg: 8321 | total: 8555
   */

  import type { ScoreDistribution } from '$lib/types/custom-model';

  interface Props {
    distribution: ScoreDistribution;
    /** When true, render a smaller inline variant. */
    compact?: boolean;
  }

  let { distribution, compact = false }: Props = $props();

  // --------------------------------------------------------------
  // Derived values
  // --------------------------------------------------------------

  const binCounts = $derived(distribution.bin_counts ?? []);
  const binEdges = $derived(distribution.bin_edges ?? []);
  const maxCount = $derived(binCounts.length > 0 ? Math.max(1, ...binCounts) : 1);
  const meanScore = $derived(distribution.mean_score ?? 0);
  const totalScored = $derived(distribution.total_scored ?? 0);
  const positiveCount = $derived(distribution.positive_count ?? 0);
  const negativeCount = $derived(distribution.negative_count ?? 0);

  // Chart height in pixels. Compact mode uses roughly half the height.
  const chartHeightPx = $derived(compact ? 48 : 96);

  // Clamp mean into [0, 1] so the marker never falls outside the chart.
  const meanClamped = $derived(Math.max(0, Math.min(1, meanScore)));
  const meanPercent = $derived(meanClamped * 100);

  /**
   * Format a number as a short, human-readable string (e.g. 1.2k for 1234).
   */
  function formatCount(n: number): string {
    if (n < 1000) return n.toString();
    if (n < 1_000_000) return (n / 1000).toFixed(n < 10_000 ? 1 : 0) + 'k';
    return (n / 1_000_000).toFixed(1) + 'M';
  }

  /**
   * Height of a single bar as a percentage of the chart area.
   * Guarantees a minimum 2% height for non-zero bins so they remain visible.
   */
  function barHeight(count: number): number {
    if (count <= 0) return 0;
    const pct = (count / maxCount) * 100;
    return Math.max(2, pct);
  }

  /**
   * Tooltip text for a bar describing its bin range and count.
   */
  function barTooltip(index: number): string {
    const lo = binEdges[index] ?? 0;
    const hi = binEdges[index + 1] ?? 1;
    const c = binCounts[index] ?? 0;
    return `${lo.toFixed(2)}–${hi.toFixed(2)}: ${c.toLocaleString()}`;
  }
</script>

<div class="space-y-2">
  <!-- Header row: label + mean -->
  <div class="flex items-baseline justify-between gap-2">
    <span
      class="font-medium text-stone-600 dark:text-stone-300"
      class:text-xs={compact}
      class:text-sm={!compact}
    >
      Score distribution
    </span>
    <span
      class="font-mono text-stone-500 dark:text-stone-400"
      class:text-[10px]={compact}
      class:text-xs={!compact}
    >
      mean {meanScore.toFixed(3)}
    </span>
  </div>

  <!-- Chart area -->
  <div
    class="relative w-full rounded border border-stone-200 bg-stone-50 dark:border-stone-700 dark:bg-stone-900"
    style="height: {chartHeightPx}px;"
  >
    <!-- Bars container: flex row with 20 equal-width columns -->
    <div class="absolute inset-0 flex items-end gap-[1px] px-1 pb-1 pt-1">
      {#each binCounts as count, i (i)}
        <div
          class="relative flex-1 rounded-sm bg-stone-400/70 transition-colors hover:bg-primary/80 dark:bg-stone-500/70"
          style="height: {barHeight(count)}%;"
          title={barTooltip(i)}
          aria-label={barTooltip(i)}
        ></div>
      {/each}
    </div>

    <!-- Mean marker: dashed vertical line -->
    {#if totalScored > 0}
      <div
        class="pointer-events-none absolute top-0 bottom-0 border-l border-dashed border-primary"
        style="left: {meanPercent}%;"
        aria-hidden="true"
      ></div>
    {/if}
  </div>

  <!-- X-axis labels -->
  <div
    class="flex justify-between font-mono text-stone-400 dark:text-stone-500"
    class:text-[10px]={compact}
    class:text-xs={!compact}
  >
    <span>0.0</span>
    <span>0.5</span>
    <span>1.0</span>
  </div>

  <!-- Summary line -->
  <div
    class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-stone-500 dark:text-stone-400"
    class:text-[10px]={compact}
    class:text-xs={!compact}
  >
    <span>mean: <span class="font-mono text-stone-700 dark:text-stone-200">{meanScore.toFixed(3)}</span></span>
    <span class="text-stone-300 dark:text-stone-600">·</span>
    <span>pos (&ge;0.5): <span class="font-mono text-stone-700 dark:text-stone-200">{formatCount(positiveCount)}</span></span>
    <span class="text-stone-300 dark:text-stone-600">·</span>
    <span>neg: <span class="font-mono text-stone-700 dark:text-stone-200">{formatCount(negativeCount)}</span></span>
    <span class="text-stone-300 dark:text-stone-600">·</span>
    <span>total: <span class="font-mono text-stone-700 dark:text-stone-200">{formatCount(totalScored)}</span></span>
  </div>
</div>
