<script lang="ts">
  /**
   * DatetimePreviewTable - Table showing parsed datetime results for sample filenames.
   * Displays success/failure status with parsed datetime or error message.
   */
  import { getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { DatetimeTestResult } from '$lib/types/data';

  interface Props {
    results: DatetimeTestResult[];
    timezone?: string;
    /** Number of results to show; 0 means all */
    limit?: number;
    /** Border/header color variant */
    variant?: 'green' | 'default';
  }

  let {
    results,
    timezone = '',
    limit = 0,
    variant = 'default',
  }: Props = $props();

  const displayResults = $derived(limit > 0 ? results.slice(0, limit) : results);

  const headerClass = $derived(
    variant === 'green'
      ? 'border-b border-green-100 bg-green-50'
      : 'border-b border-stone-200 bg-stone-50'
  );
  const thClass = $derived(
    variant === 'green'
      ? 'font-medium text-green-700'
      : 'font-medium text-stone-600'
  );
  const borderClass = $derived(
    variant === 'green' ? 'border-green-200' : 'border-stone-200'
  );

  function formatParsedDatetime(dt: string | null): string {
    if (!dt) return '-';
    try {
      return new Date(dt).toLocaleString(getLocale());
    } catch {
      return dt;
    }
  }
</script>

<div class="overflow-x-auto rounded-md border {borderClass} bg-surface-card">
  {#if timezone}
    <p class="px-3 pt-2 text-xs text-primary-600">Times shown in {timezone}</p>
  {/if}
  <table class="w-full text-xs">
    <thead>
      <tr class={headerClass}>
        <th class="px-3 py-2 text-left {thClass}">{m.datetime_config_preview_filename()}</th>
        <th class="px-3 py-2 text-left {thClass}">{m.datetime_config_preview_datetime()}</th>
        <th class="w-12 px-3 py-2 text-center {thClass}">{m.datetime_config_preview_status()}</th>
      </tr>
    </thead>
    <tbody>
      {#each displayResults as result}
        <tr class="border-b border-stone-100 last:border-0 {result.success ? '' : 'bg-red-50'}">
          <td class="px-3 py-1.5 font-mono text-stone-700">{result.filename}</td>
          <td class="px-3 py-1.5 text-stone-600">
            {#if result.success}
              {formatParsedDatetime(result.parsed_datetime)}
            {:else}
              <span class="text-red-500">{result.error ?? 'Parse failed'}</span>
            {/if}
          </td>
          <td class="px-3 py-1.5 text-center">
            {#if result.success}
              <svg
                class="mx-auto h-4 w-4 text-green-600"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2.5"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-label="Success"
              >
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            {:else}
              <svg
                class="mx-auto h-4 w-4 text-red-500"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-label="Failed"
              >
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
