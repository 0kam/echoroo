<script lang="ts">
  /**
   * Modal for configuring datetime pattern parsing on dataset recordings.
   * Supports auto-detect, preset formats, and a click-to-select custom format UI.
   */

  import { createMutation } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages';
  import { autoDetectDatetime, testDatetimePattern, applyDatetimePattern } from '$lib/api/datasets';
  import type { DatetimeAutoDetectResult, DatetimeTestResult } from '$lib/types/data';
  import { getLocale } from '$lib/paraglide/runtime';

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
  // 'auto-detect' | 'auto-confirm' | 'manual'
  // auto-confirm: auto-detect succeeded, showing results + apply button (no manual config)
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
  let timezone = $state(currentTimezone ?? '');

  // ── Manual config state ────────────────────────────────────────────────────
  // Use first sample filename for the custom format UI
  const sampleFilename = $derived(sampleFilenames[0] ?? '');

  // Currently active pattern and format (set from assignments OR preset/auto-detect)
  let activePattern = $state<string | null>(currentPattern);
  let activeFormat = $state<string | null>(currentFormat);

  // Preview test results
  let previewResults = $state<DatetimeTestResult[] | null>(null);
  let previewError = $state<string | null>(null);

  // Apply result
  let applySuccess = $state<string | null>(null);
  let applyError = $state<string | null>(null);

  // ── Click-to-select state ─────────────────────────────────────────────────

  type DatetimePart = 'Y' | 'M' | 'D' | 'h' | 'm' | 's';

  // Selection state
  let selectionStart = $state<number | null>(null);
  let selectionEnd = $state<number | null>(null);
  let isSelecting = $state(false);

  // Assignment state - maps part to [start, end] range (inclusive)
  let assignments = $state<Map<DatetimePart, [number, number]>>(new Map());

  const PART_COLORS: Record<DatetimePart, { bg: string; text: string; label: () => string }> = {
    Y: { bg: 'bg-primary-200', text: 'text-primary-900', label: () => m.datetime_config_year() },
    M: { bg: 'bg-green-200', text: 'text-green-900', label: () => m.datetime_config_month() },
    D: { bg: 'bg-orange-200', text: 'text-orange-900', label: () => m.datetime_config_day() },
    h: { bg: 'bg-red-200', text: 'text-red-900', label: () => m.datetime_config_hour() },
    m: { bg: 'bg-purple-200', text: 'text-purple-900', label: () => m.datetime_config_minute() },
    s: { bg: 'bg-teal-200', text: 'text-teal-900', label: () => m.datetime_config_second() },
  };

  const PART_KEYS: DatetimePart[] = ['Y', 'M', 'D', 'h', 'm', 's'];

  function getCharColorClass(index: number): string {
    for (const part of PART_KEYS) {
      const range = assignments.get(part);
      if (range && index >= range[0] && index <= range[1]) {
        return `${PART_COLORS[part].bg} ${PART_COLORS[part].text}`;
      }
    }
    return 'bg-stone-100 text-stone-700';
  }

  function isInSelection(index: number): boolean {
    if (selectionStart === null || selectionEnd === null) return false;
    const min = Math.min(selectionStart, selectionEnd);
    const max = Math.max(selectionStart, selectionEnd);
    return index >= min && index <= max;
  }

  function startSelection(index: number) {
    selectionStart = index;
    selectionEnd = index;
    isSelecting = true;
  }

  function extendSelection(index: number) {
    if (isSelecting) {
      selectionEnd = index;
    }
  }

  function endSelection() {
    isSelecting = false;
  }

  function assignPart(part: DatetimePart) {
    if (selectionStart === null || selectionEnd === null) return;
    const min = Math.min(selectionStart, selectionEnd);
    const max = Math.max(selectionStart, selectionEnd);

    const newAssignments = new Map(assignments);
    newAssignments.set(part, [min, max]);
    assignments = newAssignments;

    // Clear selection after assigning
    selectionStart = null;
    selectionEnd = null;
  }

  function clearAssignment(part: DatetimePart) {
    const newAssignments = new Map(assignments);
    newAssignments.delete(part);
    assignments = newAssignments;
  }

  function clearAllAssignments() {
    assignments = new Map();
    selectionStart = null;
    selectionEnd = null;
  }

  // Document-level mouseup to end selection if released outside the grid
  $effect(() => {
    const handler = () => { isSelecting = false; };
    document.addEventListener('mouseup', handler);
    return () => document.removeEventListener('mouseup', handler);
  });

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

    // Sort assignments by start position
    const sorted = ([...asgn.entries()] as [DatetimePart, [number, number]][])
      .sort((a, b) => a[1][0] - b[1][0]);

    let pattern = '';
    let formatStr = '';
    let pos = sorted[0]![1][0]; // start at first assignment's start
    const overallEnd = sorted[sorted.length - 1]![1][1];

    for (const [part, [start, end]] of sorted) {
      // Add literal characters between previous end and this start
      if (pos < start) {
        for (let i = pos; i < start; i++) {
          const ch = filename[i] ?? '';
          pattern += escapeRegex(ch);
          formatStr += ch;
        }
      }

      // Add datetime part
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
   * Map a format string + matched string back to per-character assignments.
   */
  function formatToAssignments(
    formatStr: string,
    matchStart: number,
    matchedStr: string
  ): Map<DatetimePart, [number, number]> {
    const result = new Map<DatetimePart, [number, number]>();
    let pos = matchStart; // position in filename
    let fi = 0; // position in format string
    let mi = 0; // position in matchedStr

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
          mi += len;
        }
        fi += 2;
      } else {
        // Literal character - skip one character in matched string and filename
        pos += 1;
        mi += 1;
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

    // Try to map assignments from the sample filename
    if (sampleFilename) {
      try {
        const regex = new RegExp(preset.pattern);
        const match = sampleFilename.match(regex);
        if (match && match.index !== undefined) {
          const matchStart = match.index;
          const matchStr = match[0] ?? '';
          assignments = formatToAssignments(preset.format, matchStart, matchStr);
        } else {
          assignments = new Map();
        }
      } catch {
        assignments = new Map();
      }
    } else {
      assignments = new Map();
    }

    selectionStart = null;
    selectionEnd = null;
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
    // Go to auto-confirm: show results + apply button, skip manual config
    step = 'auto-confirm';
  }

  function formatParsedDatetime(dt: string | null): string {
    if (!dt) return '-';
    try {
      return new Date(dt).toLocaleString(getLocale());
    } catch {
      return dt;
    }
  }

  // ── Derived: current selection range (normalized) ─────────────────────────
  const currentSelectionRange = $derived(
    selectionStart !== null && selectionEnd !== null
      ? { min: Math.min(selectionStart, selectionEnd), max: Math.max(selectionStart, selectionEnd) }
      : null
  );

  const hasSelection = $derived(currentSelectionRange !== null);

  // Sorted assignments for display
  const sortedAssignments = $derived(
    ([...assignments.entries()] as [DatetimePart, [number, number]][])
      .sort((a, b) => a[1][0] - b[1][0])
  );
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
        <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <line x1="18" y1="6" x2="6" y2="18" stroke-width="2" />
          <line x1="6" y1="6" x2="18" y2="18" stroke-width="2" />
        </svg>
      </button>
    </div>

    <!-- Body (scrollable) -->
    <div class="flex-1 overflow-y-auto p-6 space-y-6">

      <!-- Auto-detect section -->
      {#if isAutoDetecting}
        <div class="flex items-center gap-3 rounded-lg border border-primary-200 bg-primary-50 px-4 py-3">
          <svg class="h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          <span class="text-sm text-primary-700">{m.datetime_config_auto_detecting()}</span>
        </div>
      {:else if autoDetectResult?.detected && step === 'auto-detect'}
        <!-- Auto-detect success -->
        <div class="rounded-lg border border-green-200 bg-green-50 p-4 space-y-3">
          <div class="flex items-center gap-2">
            <div class="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-green-600">
              <svg class="h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </div>
            <p class="text-sm font-medium text-green-800">
              {m.datetime_config_auto_detected({ name: autoDetectResult.preset_name ?? 'Custom' })}
            </p>
          </div>

          <div class="rounded-md bg-surface-card/60 px-3 py-2 text-xs font-mono text-stone-700 border border-green-200">
            {autoDetectResult.format_str}
          </div>

          <!-- Preview of auto-detect results -->
          {#if autoDetectResult.results.length > 0}
            <div class="overflow-x-auto rounded-md border border-green-200 bg-surface-card">
              <table class="w-full text-xs">
                <thead>
                  <tr class="border-b border-green-100 bg-green-50">
                    <th class="px-3 py-2 text-left font-medium text-green-700">{m.datetime_config_preview_filename()}</th>
                    <th class="px-3 py-2 text-left font-medium text-green-700">{m.datetime_config_preview_datetime()}</th>
                    <th class="w-12 px-3 py-2 text-center font-medium text-green-700">{m.datetime_config_preview_status()}</th>
                  </tr>
                </thead>
                <tbody>
                  {#each autoDetectResult.results.slice(0, 5) as result}
                    <tr class="border-b border-stone-100 last:border-0">
                      <td class="px-3 py-1.5 font-mono text-stone-700">{result.filename}</td>
                      <td class="px-3 py-1.5 text-stone-600">{formatParsedDatetime(result.parsed_datetime)}</td>
                      <td class="px-3 py-1.5 text-center">
                        {#if result.success}
                          <svg class="mx-auto h-4 w-4 text-green-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="20 6 9 17 4 12"></polyline>
                          </svg>
                        {:else}
                          <svg class="mx-auto h-4 w-4 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                          </svg>
                        {/if}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}

          <div class="flex gap-2">
            <button
              onclick={useAutoDetectedPattern}
              class="rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-green-700"
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
        <div class="rounded-lg border border-yellow-200 bg-yellow-50 px-4 py-3 text-sm text-yellow-800">
          {m.datetime_config_auto_detect_failed()}
        </div>
      {/if}

      <!-- Auto-confirm: auto-detect succeeded, user clicked "Use this pattern" -->
      {#if step === 'auto-confirm'}
        <div class="space-y-4">
          <!-- Confirmed pattern info -->
          <div class="rounded-lg border border-green-200 bg-green-50 p-4 space-y-3">
            <div class="flex items-center gap-2">
              <div class="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-green-600">
                <svg class="h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
              </div>
              <p class="text-sm font-medium text-green-800">
                {m.datetime_config_auto_detected({ name: autoDetectResult?.preset_name ?? 'Custom' })}
              </p>
            </div>
            <div class="rounded-md bg-surface-card/60 px-3 py-2 text-xs font-mono text-stone-700 border border-green-200">
              {activeFormat}
            </div>
          </div>

          <!-- Timezone selector -->
          <div class="flex flex-col gap-1.5">
            <label class="text-sm font-medium text-stone-700" for="modal-timezone-auto">
              {m.datetime_config_timezone_label()}
            </label>
            <select
              id="modal-timezone-auto"
              bind:value={timezone}
              class="rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm focus:border-primary-400 focus:outline-none focus:ring-1 focus:ring-primary-400"
            >
              <option value="">{m.datetime_config_timezone_none()}</option>
              <optgroup label="UTC">
                <option value="UTC">UTC</option>
              </optgroup>
              <optgroup label="Asia">
                <option value="Asia/Tokyo">Asia/Tokyo (JST, UTC+9)</option>
                <option value="Asia/Shanghai">Asia/Shanghai (CST, UTC+8)</option>
                <option value="Asia/Kolkata">Asia/Kolkata (IST, UTC+5:30)</option>
                <option value="Asia/Seoul">Asia/Seoul (KST, UTC+9)</option>
              </optgroup>
              <optgroup label="Australia / Pacific">
                <option value="Australia/Sydney">Australia/Sydney (AEST, UTC+10)</option>
                <option value="Pacific/Auckland">Pacific/Auckland (NZST, UTC+12)</option>
              </optgroup>
              <optgroup label="Europe">
                <option value="Europe/London">Europe/London (GMT, UTC+0)</option>
                <option value="Europe/Paris">Europe/Paris (CET, UTC+1)</option>
                <option value="Europe/Berlin">Europe/Berlin (CET, UTC+1)</option>
              </optgroup>
              <optgroup label="Americas">
                <option value="America/New_York">America/New_York (EST, UTC-5)</option>
                <option value="America/Chicago">America/Chicago (CST, UTC-6)</option>
                <option value="America/Denver">America/Denver (MST, UTC-7)</option>
                <option value="America/Los_Angeles">America/Los_Angeles (PST, UTC-8)</option>
                <option value="America/Sao_Paulo">America/Sao Paulo (BRT, UTC-3)</option>
              </optgroup>
              <optgroup label="Africa">
                <option value="Africa/Nairobi">Africa/Nairobi (EAT, UTC+3)</option>
              </optgroup>
            </select>
            <p class="text-xs text-stone-500">{m.datetime_config_timezone_hint()}</p>
          </div>

          <!-- Preview results table -->
          {#if previewResults && previewResults.length > 0}
            <div>
              <h4 class="mb-3 text-sm font-semibold text-stone-700">{m.datetime_config_preview_title()}</h4>
              {#if timezone}
                <p class="mb-2 text-xs text-primary-600">Times shown in {timezone}</p>
              {/if}
              <div class="overflow-x-auto rounded-md border border-stone-200">
                <table class="w-full text-xs">
                  <thead>
                    <tr class="border-b border-stone-200 bg-stone-50">
                      <th class="px-3 py-2 text-left font-medium text-stone-600">{m.datetime_config_preview_filename()}</th>
                      <th class="px-3 py-2 text-left font-medium text-stone-600">{m.datetime_config_preview_datetime()}</th>
                      <th class="w-12 px-3 py-2 text-center font-medium text-stone-600">{m.datetime_config_preview_status()}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each previewResults as result}
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
                            <svg class="mx-auto h-4 w-4 text-green-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                              <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                          {:else}
                            <svg class="mx-auto h-4 w-4 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                            </svg>
                          {/if}
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            </div>
          {/if}

          <!-- Apply success / error feedback -->
          {#if applySuccess}
            <div class="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
              <svg class="h-4 w-4 flex-shrink-0 text-green-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
              {applySuccess}
            </div>
          {/if}
          {#if applyError}
            <div class="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
              {applyError}
            </div>
          {/if}

          <!-- Link to switch to manual config -->
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

      <!-- Manual configuration (always shown when step === 'manual') -->
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

            <!-- Color legend -->
            <div class="mb-3 flex flex-wrap gap-2">
              {#each PART_KEYS as part}
                <span class="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium {PART_COLORS[part].bg} {PART_COLORS[part].text}">
                  {PART_COLORS[part].label()}
                </span>
              {/each}
            </div>

            <!-- Filename character grid (clickable) -->
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div
              class="overflow-x-auto rounded-t-md border border-stone-300 bg-stone-50 px-3 py-2 select-none"
              onmouseleave={() => { if (isSelecting) isSelecting = false; }}
            >
              <div class="flex flex-wrap font-mono text-sm leading-relaxed gap-0.5">
                {#each sampleFilename.split('') as char, i}
                  <button
                    type="button"
                    class="inline-flex items-center justify-center w-6 h-7 border rounded-sm cursor-pointer transition-colors
                      {getCharColorClass(i)}
                      {isInSelection(i)
                        ? 'ring-2 ring-primary-500 ring-inset border-primary-400'
                        : 'border-transparent hover:border-stone-400'}"
                    onmousedown={(e) => { e.preventDefault(); startSelection(i); }}
                    onmouseenter={() => extendSelection(i)}
                    onmouseup={() => endSelection()}
                    aria-label="{char} at position {i}"
                  >{char}</button>
                {/each}
              </div>
            </div>

            <!-- Assign buttons -->
            <div class="rounded-b-md border border-t-0 border-stone-300 bg-surface-card px-3 py-2.5">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-xs text-stone-500 shrink-0">{m.datetime_config_assign_part()}</span>
                {#each PART_KEYS as part}
                  <button
                    type="button"
                    disabled={!hasSelection}
                    onclick={() => assignPart(part)}
                    class="inline-flex items-center rounded px-2 py-1 text-xs font-medium transition-colors
                      {PART_COLORS[part].bg} {PART_COLORS[part].text}
                      disabled:opacity-40 disabled:cursor-not-allowed
                      hover:opacity-80 active:opacity-60"
                  >
                    {PART_COLORS[part].label()}
                  </button>
                {/each}
                {#if assignments.size > 0}
                  <button
                    type="button"
                    onclick={clearAllAssignments}
                    class="inline-flex items-center rounded border border-stone-300 bg-surface-card px-2 py-1 text-xs font-medium text-stone-600 transition-colors hover:bg-stone-50 hover:text-red-600 hover:border-red-300"
                  >
                    {m.datetime_config_clear_all()}
                  </button>
                {/if}
              </div>

              {#if !hasSelection && assignments.size === 0}
                <p class="mt-1.5 text-xs text-stone-400">{m.datetime_config_no_selection()}</p>
              {/if}
            </div>

            <!-- Current assignment badges -->
            {#if sortedAssignments.length > 0}
              <div class="flex flex-wrap gap-2 mt-2">
                {#each sortedAssignments as [part, [start, end]]}
                  <div class="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs {PART_COLORS[part].bg} {PART_COLORS[part].text}">
                    <span>{PART_COLORS[part].label()}: "{sampleFilename.slice(start, end + 1)}"</span>
                    <button
                      type="button"
                      class="ml-1 hover:opacity-70 font-semibold"
                      onclick={() => clearAssignment(part)}
                      aria-label="Remove {PART_COLORS[part].label()} assignment"
                    >x</button>
                  </div>
                {/each}
              </div>
            {/if}

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
        <div class="flex flex-col gap-1.5">
          <label class="text-sm font-medium text-stone-700" for="modal-timezone">
            {m.datetime_config_timezone_label()}
          </label>
          <select
            id="modal-timezone"
            bind:value={timezone}
            class="rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm focus:border-primary-400 focus:outline-none focus:ring-1 focus:ring-primary-400"
          >
            <option value="">{m.datetime_config_timezone_none()}</option>
            <optgroup label="UTC">
              <option value="UTC">UTC</option>
            </optgroup>
            <optgroup label="Asia">
              <option value="Asia/Tokyo">Asia/Tokyo (JST, UTC+9)</option>
              <option value="Asia/Shanghai">Asia/Shanghai (CST, UTC+8)</option>
              <option value="Asia/Kolkata">Asia/Kolkata (IST, UTC+5:30)</option>
              <option value="Asia/Seoul">Asia/Seoul (KST, UTC+9)</option>
            </optgroup>
            <optgroup label="Australia / Pacific">
              <option value="Australia/Sydney">Australia/Sydney (AEST, UTC+10)</option>
              <option value="Pacific/Auckland">Pacific/Auckland (NZST, UTC+12)</option>
            </optgroup>
            <optgroup label="Europe">
              <option value="Europe/London">Europe/London (GMT, UTC+0)</option>
              <option value="Europe/Paris">Europe/Paris (CET, UTC+1)</option>
              <option value="Europe/Berlin">Europe/Berlin (CET, UTC+1)</option>
            </optgroup>
            <optgroup label="Americas">
              <option value="America/New_York">America/New_York (EST, UTC-5)</option>
              <option value="America/Chicago">America/Chicago (CST, UTC-6)</option>
              <option value="America/Denver">America/Denver (MST, UTC-7)</option>
              <option value="America/Los_Angeles">America/Los_Angeles (PST, UTC-8)</option>
              <option value="America/Sao_Paulo">America/Sao Paulo (BRT, UTC-3)</option>
            </optgroup>
            <optgroup label="Africa">
              <option value="Africa/Nairobi">Africa/Nairobi (EAT, UTC+3)</option>
            </optgroup>
          </select>
          <p class="text-xs text-stone-500">{m.datetime_config_timezone_hint()}</p>
        </div>

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
              <div class="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
                {previewError}
              </div>
            {/if}

            {#if previewResults}
              {#if timezone}
                <p class="mb-2 text-xs text-primary-600">Times shown in {timezone}</p>
              {/if}
              <div class="overflow-x-auto rounded-md border border-stone-200">
                <table class="w-full text-xs">
                  <thead>
                    <tr class="border-b border-stone-200 bg-stone-50">
                      <th class="px-3 py-2 text-left font-medium text-stone-600">{m.datetime_config_preview_filename()}</th>
                      <th class="px-3 py-2 text-left font-medium text-stone-600">{m.datetime_config_preview_datetime()}</th>
                      <th class="w-12 px-3 py-2 text-center font-medium text-stone-600">{m.datetime_config_preview_status()}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each previewResults as result}
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
                            <svg class="mx-auto h-4 w-4 text-green-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                              <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                          {:else}
                            <svg class="mx-auto h-4 w-4 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                            </svg>
                          {/if}
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          </div>
        {/if}

        <!-- Apply success / error feedback -->
        {#if applySuccess}
          <div class="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
            <svg class="h-4 w-4 flex-shrink-0 text-green-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            {applySuccess}
          </div>
        {/if}
        {#if applyError}
          <div class="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
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
          class="flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {#if $applyMut.isPending}
            <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
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
