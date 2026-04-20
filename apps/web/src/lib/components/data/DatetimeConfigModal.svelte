<script lang="ts">
  /**
   * Modal for configuring datetime pattern parsing on dataset recordings.
   * Supports auto-detect, preset formats, and a click-to-select custom format UI.
   *
   * Sub-components:
   * - DatetimePreviewTable: renders parsed datetime results table
   * - TimezoneSelect: timezone dropdown
   * - FilenameCharGrid: interactive character selection grid
   */

  import { untrack } from 'svelte';
  import { createMutation } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages';
  import { autoDetectDatetime, testDatetimePattern, applyDatetimePattern } from '$lib/api/datasets';
  import type { DatetimeAutoDetectResult, DatetimeTestResult } from '$lib/types/data';
  import DatetimePreviewTable from './DatetimePreviewTable.svelte';
  import TimezoneSelect from './TimezoneSelect.svelte';
  import FilenameCharGrid from './FilenameCharGrid.svelte';

  interface Props {
    projectId: string;
    datasetId: string;
    currentPattern: string | null;
    currentFormat: string | null;
    currentTimezone: string | null;
    sampleFilenames: string[];
    onClose: () => void;
  }

  let {
    projectId,
    datasetId,
    currentPattern,
    currentFormat,
    currentTimezone,
    sampleFilenames,
    onClose,
  }: Props = $props();

  // ── Step management ────────────────────────────────────────────────────────
  type Step = 'auto-detect' | 'auto-confirm' | 'manual';
  let step = $state<Step>('auto-detect');

  // ── Auto-detect state ──────────────────────────────────────────────────────
  let autoDetectResult = $state<DatetimeAutoDetectResult | null>(null);
  let autoDetectError = $state<string | null>(null);
  let isAutoDetecting = $state(false);

  // Run auto-detect on mount
  $effect(() => {
    runAutoDetect();
  });

  async function runAutoDetect() {
    isAutoDetecting = true;
    autoDetectError = null;
    try {
      autoDetectResult = await autoDetectDatetime(projectId, datasetId);
      if (!autoDetectResult.detected) {
        step = 'manual';
      }
    } catch (e) {
      autoDetectError = e instanceof Error ? e.message : 'Auto-detect failed';
      step = 'manual';
    } finally {
      isAutoDetecting = false;
    }
  }

  // ── Timezone state ────────────────────────────────────────────────────────
  // Initial value is captured once from the prop; the user can edit it
  // afterwards via the timezone dropdown.
  let timezone = $state(untrack(() => currentTimezone ?? ''));

  // ── Manual config state ────────────────────────────────────────────────────
  const sampleFilename = $derived(sampleFilenames[0] ?? '');

  let activePattern = $state<string | null>(untrack(() => currentPattern));
  let activeFormat = $state<string | null>(untrack(() => currentFormat));

  // Preview test results
  let previewResults = $state<DatetimeTestResult[] | null>(null);
  let previewError = $state<string | null>(null);

  // Apply result
  let applySuccess = $state<string | null>(null);
  let applyError = $state<string | null>(null);

  // ── Click-to-select state ─────────────────────────────────────────────────
  type DatetimePart = 'Y' | 'M' | 'D' | 'h' | 'm' | 's';
  let assignments = $state<Map<DatetimePart, [number, number]>>(new Map());

  // ── Pattern generation from assignments ───────────────────────────────────

  function escapeRegex(str: string): string {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  const FORMAT_MAP: Record<DatetimePart, string> = {
    Y: '%Y', M: '%m', D: '%d', h: '%H', m: '%M', s: '%S',
  };

  function generatePatternFromAssignments(
    asgn: Map<DatetimePart, [number, number]>,
    filename: string
  ): { pattern: string; formatStr: string } | null {
    if (asgn.size === 0 || !filename) return null;

    const sorted = ([...asgn.entries()] as [DatetimePart, [number, number]][])
      .sort((a, b) => a[1][0] - b[1][0]);

    let pattern = '';
    let formatStr = '';
    let pos = sorted[0]![1][0];

    for (const [part, [start, end]] of sorted) {
      if (pos < start) {
        for (let i = pos; i < start; i++) {
          const ch = filename[i] ?? '';
          pattern += escapeRegex(ch);
          formatStr += ch;
        }
      }

      const len = end - start + 1;
      pattern += `\\d{${len}}`;
      formatStr += FORMAT_MAP[part];
      pos = end + 1;
    }

    if (!pattern) return null;
    return { pattern: `(${pattern})`, formatStr };
  }

  const assignmentResult = $derived(
    generatePatternFromAssignments(assignments, sampleFilename)
  );

  // Update active pattern/format when assignments change
  $effect(() => {
    if (assignmentResult) {
      activePattern = assignmentResult.pattern;
      activeFormat = assignmentResult.formatStr;
    }
  });

  // ── Presets ────────────────────────────────────────────────────────────────
  interface Preset {
    name: string;
    label: string;
    pattern: string;
    format: string;
    example: string;
  }

  const PRESETS: Preset[] = [
    {
      name: 'AudioMoth / Wildlife Acoustics',
      label: 'AudioMoth / Wildlife Acoustics (20240315_143000)',
      pattern: '(\\d{8}_\\d{6})',
      format: '%Y%m%d_%H%M%S',
      example: '20240315_143000.WAV',
    },
    {
      name: 'ISO datetime',
      label: 'ISO (2024-03-15T14:30:00)',
      pattern: '(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2})',
      format: '%Y-%m-%dT%H:%M:%S',
      example: '2024-03-15T14:30:00.wav',
    },
    {
      name: 'Compact',
      label: 'Compact (20240315143000)',
      pattern: '(\\d{14})',
      format: '%Y%m%d%H%M%S',
      example: '20240315143000.wav',
    },
  ];

  /**
   * Map a format string + match position back to per-character assignments.
   */
  function formatToAssignments(
    formatStr: string,
    matchStart: number,
    _matchedStr: string
  ): Map<DatetimePart, [number, number]> {
    const result = new Map<DatetimePart, [number, number]>();
    let pos = matchStart;
    let fi = 0;

    while (fi < formatStr.length) {
      if (formatStr[fi] === '%' && fi + 1 < formatStr.length) {
        const spec = formatStr[fi + 1];
        let part: DatetimePart | null = null;
        let len = 0;

        switch (spec) {
          case 'Y': part = 'Y'; len = 4; break;
          case 'm': part = 'M'; len = 2; break;
          case 'd': part = 'D'; len = 2; break;
          case 'H': part = 'h'; len = 2; break;
          case 'M': part = 'm'; len = 2; break;
          case 'S': part = 's'; len = 2; break;
        }

        if (part !== null) {
          result.set(part, [pos, pos + len - 1]);
          pos += len;
        }
        fi += 2;
      } else {
        pos += 1;
        fi += 1;
      }
    }

    return result;
  }

  function applyPreset(preset: Preset) {
    activePattern = preset.pattern;
    activeFormat = preset.format;
    previewResults = null;
    previewError = null;
    applySuccess = null;
    applyError = null;

    if (sampleFilename) {
      try {
        const regex = new RegExp(preset.pattern);
        const match = sampleFilename.match(regex);
        if (match && match.index !== undefined) {
          assignments = formatToAssignments(preset.format, match.index, match[0] ?? '');
        } else {
          assignments = new Map();
        }
      } catch {
        assignments = new Map();
      }
    } else {
      assignments = new Map();
    }
  }

  // ── Mutations ──────────────────────────────────────────────────────────────

  const testMut = createMutation({
    mutationFn: () => {
      if (!activePattern || !activeFormat) throw new Error('No pattern set');
      return testDatetimePattern(projectId, datasetId, activePattern, activeFormat, timezone || undefined);
    },
    onSuccess: (results) => {
      previewResults = results;
      previewError = null;
    },
    onError: (err: Error) => {
      previewError = err.message;
      previewResults = null;
    },
  });

  const applyMut = createMutation({
    mutationFn: () => {
      if (!activePattern || !activeFormat) throw new Error('No pattern set');
      return applyDatetimePattern(projectId, datasetId, activePattern, activeFormat, timezone || undefined);
    },
    onSuccess: (result) => {
      applySuccess = m.datetime_config_apply_success({ count: result.total_recordings });
      applyError = null;
    },
    onError: (err: Error) => {
      applyError = err.message;
      applySuccess = null;
    },
  });

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onClose();
  }

  // ── Use auto-detected pattern ──────────────────────────────────────────────
  function useAutoDetectedPattern() {
    if (!autoDetectResult) return;
    activePattern = autoDetectResult.pattern;
    activeFormat = autoDetectResult.format_str;
    previewResults = autoDetectResult.results;
    previewError = null;
    applySuccess = null;
    applyError = null;
    step = 'auto-confirm';
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
  class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
  onclick={onClose}
  role="dialog"
  aria-modal="true"
  aria-labelledby="datetime-config-modal-title"
  tabindex="-1"
>
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    class="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg bg-surface-card shadow-xl"
    onclick={(e) => e.stopPropagation()}
    role="document"
  >
    <!-- Header -->
    <div class="flex flex-shrink-0 items-center justify-between border-b border-stone-200 px-6 py-4">
      <h3 id="datetime-config-modal-title" class="m-0 text-lg font-semibold text-stone-900">
        {m.datetime_config_modal_title()}
      </h3>
      <button
        type="button"
        onclick={onClose}
        aria-label="Close"
        class="rounded p-1 text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-600"
      >
        <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
          <line x1="18" y1="6" x2="6" y2="18" stroke-width="2" />
          <line x1="6" y1="6" x2="18" y2="18" stroke-width="2" />
        </svg>
      </button>
    </div>

    <!-- Body (scrollable) -->
    <div class="flex-1 overflow-y-auto p-6 space-y-6">

      <!-- ── Auto-detect section ─────────────────────────────────────────── -->
      {#if isAutoDetecting}
        <div class="flex items-center gap-3 rounded-lg border border-primary-200 bg-primary-50 px-4 py-3">
          <svg class="h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          <span class="text-sm text-primary-700">{m.datetime_config_auto_detecting()}</span>
        </div>
      {:else if autoDetectResult?.detected && step === 'auto-detect'}
        <!-- Auto-detect success banner -->
        <div class="rounded-lg border border-success/30 bg-success-light p-4 space-y-3">
          <div class="flex items-center gap-2">
            <div class="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-success">
              <svg class="h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </div>
            <p class="text-sm font-medium text-success">
              {m.datetime_config_auto_detected({ name: autoDetectResult.preset_name ?? 'Custom' })}
            </p>
          </div>

          <div class="rounded-md bg-surface-card/60 px-3 py-2 text-xs font-mono text-stone-700 border border-success/20">
            {autoDetectResult.format_str}
          </div>

          {#if autoDetectResult.results.length > 0}
            <DatetimePreviewTable
              results={autoDetectResult.results}
              limit={5}
              variant="green"
            />
          {/if}

          <div class="flex gap-2">
            <button
              onclick={useAutoDetectedPattern}
              class="rounded-md bg-success px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-success/80"
            >
              {m.datetime_config_use_pattern()}
            </button>
            <button
              onclick={() => { step = 'manual'; }}
              class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50"
            >
              {m.datetime_config_configure_manually()}
            </button>
          </div>
        </div>
      {:else if autoDetectError}
        <div class="rounded-lg border border-warning/30 bg-warning-light px-4 py-3 text-sm text-warning">
          {m.datetime_config_auto_detect_failed()}
        </div>
      {/if}

      <!-- ── Auto-confirm step ───────────────────────────────────────────── -->
      {#if step === 'auto-confirm'}
        <div class="space-y-4">
          <!-- Confirmed pattern info -->
          <div class="rounded-lg border border-success/30 bg-success-light p-4 space-y-3">
            <div class="flex items-center gap-2">
              <div class="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-success">
                <svg class="h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
              </div>
              <p class="text-sm font-medium text-success">
                {m.datetime_config_auto_detected({ name: autoDetectResult?.preset_name ?? 'Custom' })}
              </p>
            </div>
            <div class="rounded-md bg-surface-card/60 px-3 py-2 text-xs font-mono text-stone-700 border border-success/20">
              {activeFormat}
            </div>
          </div>

          <!-- Timezone selector -->
          <TimezoneSelect id="modal-timezone-auto" bind:value={timezone} />

          <!-- Preview results table -->
          {#if previewResults && previewResults.length > 0}
            <div>
              <h4 class="mb-3 text-sm font-semibold text-stone-700">{m.datetime_config_preview_title()}</h4>
              <DatetimePreviewTable results={previewResults} {timezone} />
            </div>
          {/if}

          <!-- Apply feedback -->
          {#if applySuccess}
            <div class="flex items-center gap-2 rounded-md border border-success/30 bg-success-light px-4 py-3 text-sm text-success">
              <svg class="h-4 w-4 flex-shrink-0 text-success" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
              {applySuccess}
            </div>
          {/if}
          {#if applyError}
            <div class="rounded-md border border-danger/30 bg-danger-light px-4 py-3 text-sm text-danger">
              {applyError}
            </div>
          {/if}

          <div class="text-center">
            <button
              type="button"
              onclick={() => { step = 'manual'; }}
              class="text-sm text-primary-600 underline hover:text-primary-800"
            >
              {m.datetime_config_configure_manually()}
            </button>
          </div>
        </div>
      {/if}

      <!-- ── Manual configuration ───────────────────────────────────────── -->
      {#if step === 'manual'}
        <!-- Presets -->
        <div>
          <h4 class="mb-3 text-sm font-semibold text-stone-700">{m.datetime_config_presets_title()}</h4>
          <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {#each PRESETS as preset}
              <button
                type="button"
                onclick={() => applyPreset(preset)}
                class="flex flex-col items-start rounded-lg border border-stone-200 px-3 py-2.5 text-left transition-colors hover:border-primary-300 hover:bg-primary-50 {activeFormat === preset.format && activePattern === preset.pattern ? 'border-primary-400 bg-primary-50' : 'bg-surface-card'}"
              >
                <span class="text-xs font-medium text-stone-900">{preset.name}</span>
                <span class="mt-0.5 font-mono text-xs text-stone-500">{preset.example}</span>
              </button>
            {/each}
          </div>
        </div>

        <!-- Click-to-select custom format UI -->
        {#if sampleFilename}
          <div>
            <h4 class="mb-1 text-sm font-semibold text-stone-700">{m.datetime_config_template_title()}</h4>
            <p class="mb-3 text-xs text-stone-500">{m.datetime_config_custom_instruction()}</p>

            <FilenameCharGrid
              filename={sampleFilename}
              {assignments}
              onAssignmentsChange={(newAssignments) => { assignments = newAssignments; }}
            />

            <!-- Pattern / format preview -->
            {#if assignmentResult}
              <div class="mt-3 rounded-md bg-stone-50 border border-stone-200 px-3 py-2 space-y-1">
                <div class="flex items-center gap-2 text-xs">
                  <span class="font-medium text-stone-500">Pattern:</span>
                  <code class="font-mono text-stone-700">{assignmentResult.pattern}</code>
                </div>
                <div class="flex items-center gap-2 text-xs">
                  <span class="font-medium text-stone-500">Format:</span>
                  <code class="font-mono text-stone-700">{assignmentResult.formatStr}</code>
                </div>
              </div>
            {/if}
          </div>
        {:else}
          <div class="rounded-lg border border-stone-200 bg-stone-50 px-4 py-6 text-center text-sm text-stone-500">
            {m.datetime_config_no_recordings()}
          </div>
        {/if}

        <!-- Timezone selector -->
        <TimezoneSelect id="modal-timezone" bind:value={timezone} />

        <!-- Test / Preview section -->
        {#if activePattern && activeFormat}
          <div>
            <div class="flex items-center justify-between mb-3">
              <h4 class="text-sm font-semibold text-stone-700">{m.datetime_config_preview_title()}</h4>
              <button
                type="button"
                onclick={() => $testMut.mutate()}
                disabled={$testMut.isPending}
                class="rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-xs font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {$testMut.isPending ? m.common_loading() : m.datetime_config_test()}
              </button>
            </div>

            {#if previewError}
              <div class="rounded-md border border-danger/30 bg-danger-light px-3 py-2 text-sm text-danger">
                {previewError}
              </div>
            {/if}

            {#if previewResults}
              <DatetimePreviewTable results={previewResults} {timezone} />
            {/if}
          </div>
        {/if}

        <!-- Apply feedback -->
        {#if applySuccess}
          <div class="flex items-center gap-2 rounded-md border border-success/30 bg-success-light px-4 py-3 text-sm text-success">
            <svg class="h-4 w-4 flex-shrink-0 text-success" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            {applySuccess}
          </div>
        {/if}
        {#if applyError}
          <div class="rounded-md border border-danger/30 bg-danger-light px-4 py-3 text-sm text-danger">
            {applyError}
          </div>
        {/if}
      {/if}
    </div>

    <!-- Footer -->
    <div class="flex flex-shrink-0 items-center justify-between gap-3 rounded-b-lg border-t border-stone-200 bg-stone-50 px-6 py-4">
      <button
        type="button"
        onclick={onClose}
        class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50"
      >
        {m.common_cancel()}
      </button>

      {#if (step === 'manual' || step === 'auto-confirm') && activePattern && activeFormat}
        <button
          type="button"
          onclick={() => $applyMut.mutate()}
          disabled={$applyMut.isPending}
          class="flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
        >
          {#if $applyMut.isPending}
            <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" opacity="0.25"></circle>
              <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            {m.datetime_config_applying()}
          {:else}
            {m.datetime_config_apply()}
          {/if}
        </button>
      {/if}
    </div>
  </div>
</div>
