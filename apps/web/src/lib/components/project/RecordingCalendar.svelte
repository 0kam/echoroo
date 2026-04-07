<script lang="ts">
  /**
   * RecordingCalendar - GitHub-style contribution calendar for recording activity.
   *
   * Displays a year x month heatmap showing recording counts per month,
   * color-coded by the number of active sites.
   */

  import type { RecordingCalendarEntry } from '$lib/types';
  import * as m from '$lib/paraglide/messages';
  import { getLocale } from '$lib/paraglide/runtime';

  interface Props {
    calendar: RecordingCalendarEntry[];
  }

  let { calendar }: Props = $props();

  const locale = $derived(getLocale());

  // Build a lookup map: "year-month" -> entry
  const entryMap = $derived(() => {
    const map = new Map<string, RecordingCalendarEntry>();
    for (const entry of calendar) {
      map.set(`${entry.year}-${entry.month}`, entry);
    }
    return map;
  });

  // Determine year range from data
  const years = $derived(() => {
    if (calendar.length === 0) return [] as number[];
    const allYears = calendar.map((e) => e.year);
    const minYear = Math.min(...allYears);
    const maxYear = Math.max(...allYears);
    const result: number[] = [];
    for (let y = minYear; y <= maxYear; y++) {
      result.push(y);
    }
    return result;
  });

  const months = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

  // Max site count for color scaling
  const maxSiteCount = $derived(() => {
    if (calendar.length === 0) return 1;
    return Math.max(...calendar.map((e) => e.site_count), 1);
  });

  /**
   * Returns a Tailwind color class based on the number of active sites.
   */
  function getCellColor(siteCount: number, max: number): string {
    if (siteCount === 0) return 'bg-stone-100';
    const ratio = siteCount / max;
    if (ratio <= 0.25) return 'bg-green-200';
    if (ratio <= 0.5) return 'bg-green-400';
    if (ratio <= 0.75) return 'bg-green-600';
    return 'bg-green-800';
  }

  /**
   * Format month label (abbreviated month name).
   */
  function getMonthLabel(month: number): string {
    const date = new Date(2000, month - 1, 1);
    return date.toLocaleString(locale, { month: 'short' });
  }

  /**
   * Format tooltip for a cell.
   */
  function getTooltip(year: number, month: number, entry: RecordingCalendarEntry | undefined): string {
    const date = new Date(year, month - 1, 1);
    const monthLabel = date.toLocaleString(locale, { year: 'numeric', month: 'long' });
    if (!entry || entry.recording_count === 0) {
      return monthLabel;
    }
    return m.project_overview_calendar_tooltip({
      month: monthLabel,
      recordings: entry.recording_count,
      sites: entry.site_count,
    });
  }

  // Tooltip state
  let tooltipText = $state('');
  let tooltipVisible = $state(false);
  let tooltipX = $state(0);
  let tooltipY = $state(0);

  function showTooltip(event: MouseEvent, year: number, month: number) {
    const entry = entryMap().get(`${year}-${month}`);
    tooltipText = getTooltip(year, month, entry);
    tooltipVisible = true;
    tooltipX = event.clientX;
    tooltipY = event.clientY;
  }

  function hideTooltip() {
    tooltipVisible = false;
  }
</script>

<div class="relative overflow-x-auto">
  <!-- Month header row -->
  <div class="mb-1 flex">
    <!-- Spacer for year labels -->
    <div class="w-12 flex-shrink-0"></div>
    {#each months as month}
      <div class="min-w-0 flex-1 text-center text-xs text-stone-500">
        {getMonthLabel(month)}
      </div>
    {/each}
  </div>

  <!-- Year rows -->
  {#each years() as year}
    <div class="mb-1.5 flex items-center">
      <!-- Year label -->
      <div class="w-12 flex-shrink-0 pr-2 text-right text-xs font-medium text-stone-600">
        {year}
      </div>
      <!-- Month cells -->
      {#each months as month}
        {@const entry = entryMap().get(`${year}-${month}`)}
        {@const siteCount = entry?.site_count ?? 0}
        <div class="min-w-0 flex-1 px-0.5">
          <button
            type="button"
            class="h-7 w-full rounded-sm {getCellColor(siteCount, maxSiteCount())} cursor-default transition-opacity hover:opacity-80 focus:outline-none"
            title={getTooltip(year, month, entry)}
            onmouseenter={(e) => showTooltip(e, year, month)}
            onmouseleave={hideTooltip}
            aria-label={getTooltip(year, month, entry)}
          ></button>
        </div>
      {/each}
    </div>
  {/each}

  <!-- Legend: min value - color gradient - max value -->
  <div class="mt-3 flex items-center gap-2 text-xs text-stone-500">
    <span>{m.project_overview_calendar_legend_sites({ count: 0 })}</span>
    <div class="h-4 w-4 rounded-sm bg-stone-100"></div>
    <div class="h-4 w-4 rounded-sm bg-green-200"></div>
    <div class="h-4 w-4 rounded-sm bg-green-400"></div>
    <div class="h-4 w-4 rounded-sm bg-green-600"></div>
    <div class="h-4 w-4 rounded-sm bg-green-800"></div>
    <span>{m.project_overview_calendar_legend_sites({ count: maxSiteCount() })}</span>
  </div>
</div>

<!-- Tooltip (fixed position) -->
{#if tooltipVisible && tooltipText}
  <div
    class="pointer-events-none fixed z-50 max-w-xs rounded bg-stone-900 px-2 py-1 text-xs text-white shadow-lg"
    style="left: {tooltipX + 12}px; top: {tooltipY - 28}px;"
  >
    {tooltipText}
  </div>
{/if}
