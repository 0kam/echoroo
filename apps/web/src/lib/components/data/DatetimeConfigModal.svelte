<script lang="ts">
  /**
   * Modal for configuring datetime pattern parsing on dataset recordings.
   * Supports auto-detect, preset formats, and a template string UI.
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
    sampleFilenames: string[];
    onClose: () => void;
  }

  let {
    projectId,
    datasetId,
    currentPattern,
    currentFormat,
    sampleFilenames,
    onClose,
  }: Props = $props();

  // ── Step management ────────────────────────────────────────────────────────
  // 'auto-detect' | 'manual'
  type Step = 'auto-detect' | 'manual';
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

  // ── Manual config state ────────────────────────────────────────────────────
  // Use first sample filename for the template UI
  const sampleFilename = $derived(sampleFilenames[0] ?? '');

  // Template string (same length as filename, filled with Y/M/D/h/m/s or spaces)
  let templateString = $state('');

  // Initialize template from current pattern if available
  $effect(() => {
    if (currentFormat && sampleFilename) {
      templateString = ' '.repeat(sampleFilename.length);
    } else if (sampleFilename) {
      templateString = ' '.repeat(sampleFilename.length);
    }
  });

  // Currently active pattern and format (derived from template OR set from preset/auto-detect)
  let activePattern = $state<string | null>(currentPattern);
  let activeFormat = $state<string | null>(currentFormat);

  // Preview test results
  let previewResults = $state<DatetimeTestResult[] | null>(null);
  let previewError = $state<string | null>(null);

  // Apply result
  let applySuccess = $state<string | null>(null);
  let applyError = $state<string | null>(null);

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
      name: 'AudioMoth',
      label: 'AudioMoth (20240315_143000)',
      pattern: '(\\d{8}_\\d{6})',
      format: '%Y%m%d_%H%M%S',
      example: '20240315_143000.WAV',
    },
    {
      name: 'Wildlife Acoustics',
      label: 'Wildlife Acoustics (20240315$143000)',
      pattern: '(\\d{8}\\$\\d{6})',
      format: '%Y%m%d$%H%M%S',
      example: 'SM4_20240315$143000.wav',
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

  function applyPreset(preset: Preset) {
    activePattern = preset.pattern;
    activeFormat = preset.format;
    templateString = ' '.repeat(sampleFilename.length);
    previewResults = null;
    previewError = null;
    applySuccess = null;
    applyError = null;
  }

  // ── Template string UI ─────────────────────────────────────────────────────

  // Color scheme for datetime markers
  const MARKER_COLORS: Record<string, string> = {
    Y: 'bg-blue-200 text-blue-900',
    M: 'bg-green-200 text-green-900',
    D: 'bg-orange-200 text-orange-900',
    h: 'bg-red-200 text-red-900',
    m: 'bg-purple-200 text-purple-900',
    s: 'bg-teal-200 text-teal-900',
  };

  // Characters that are datetime markers
  const MARKER_CHARS = new Set(['Y', 'M', 'D', 'h', 'm', 's']);

  function getTemplateCharColor(char: string): string {
    return MARKER_COLORS[char] ?? '';
  }

  function isMarker(char: string): boolean {
    return MARKER_CHARS.has(char);
  }

  /**
   * Convert a template string to a regex pattern and strptime format string.
   * Template markers: YYYY=year, MM=month, DD=day, hh=hour, mm=minute, ss=second
   * Non-marker chars between datetime region use actual filename chars as literals.
   */
  function templateToPattern(
    template: string,
    filename: string
  ): { pattern: string; formatStr: string } | null {
    if (!template.trim() || !filename) return null;

    // Find the extent of the datetime region (first to last marker)
    let firstMarker = -1;
    let lastMarker = -1;
    for (let i = 0; i < template.length; i++) {
      if (isMarker(template[i] ?? '')) {
        if (firstMarker === -1) firstMarker = i;
        lastMarker = i;
      }
    }

    if (firstMarker === -1) return null;

    // Build regex and format string for the datetime region
    let regexPart = '';
    let formatStr = '';
    let i = firstMarker;

    while (i <= lastMarker) {
      const ch = template[i];
      if (ch === 'Y') {
        // Consume up to 4 Y's
        const run = consumeRun(template, i, 'Y');
        if (run >= 4) {
          regexPart += '\\d{4}';
          formatStr += '%Y';
          i += 4;
        } else {
          regexPart += `\\d{${run}}`;
          formatStr += '%Y';
          i += run;
        }
      } else if (ch === 'M') {
        const run = consumeRun(template, i, 'M');
        if (run >= 2) {
          regexPart += '\\d{2}';
          formatStr += '%m';
          i += 2;
        } else {
          regexPart += `\\d{${run}}`;
          formatStr += '%m';
          i += run;
        }
      } else if (ch === 'D') {
        const run = consumeRun(template, i, 'D');
        if (run >= 2) {
          regexPart += '\\d{2}';
          formatStr += '%d';
          i += 2;
        } else {
          regexPart += `\\d{${run}}`;
          formatStr += '%d';
          i += run;
        }
      } else if (ch === 'h') {
        const run = consumeRun(template, i, 'h');
        if (run >= 2) {
          regexPart += '\\d{2}';
          formatStr += '%H';
          i += 2;
        } else {
          regexPart += `\\d{${run}}`;
          formatStr += '%H';
          i += run;
        }
      } else if (ch === 'm') {
        const run = consumeRun(template, i, 'm');
        if (run >= 2) {
          regexPart += '\\d{2}';
          formatStr += '%M';
          i += 2;
        } else {
          regexPart += `\\d{${run}}`;
          formatStr += '%M';
          i += run;
        }
      } else if (ch === 's') {
        const run = consumeRun(template, i, 's');
        if (run >= 2) {
          regexPart += '\\d{2}';
          formatStr += '%S';
          i += 2;
        } else {
          regexPart += `\\d{${run}}`;
          formatStr += '%S';
          i += run;
        }
      } else {
        // Non-marker: use actual filename character as literal separator
        const literal = (filename[i] ?? ch) as string;
        regexPart += escapeRegex(literal);
        formatStr += literal;
        i++;
      }
    }

    if (!regexPart) return null;

    return {
      pattern: `(${regexPart})`,
      formatStr,
    };
  }

  function consumeRun(str: string, start: number, char: string): number {
    let count = 0;
    while (start + count < str.length && str[start + count] === char) {
      count++;
    }
    return count;
  }

  function escapeRegex(str: string): string {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  // Derived pattern/format from template
  const templateResult = $derived(
    sampleFilename ? templateToPattern(templateString, sampleFilename) : null
  );

  // Update active pattern/format when template changes
  $effect(() => {
    if (templateResult) {
      activePattern = templateResult.pattern;
      activeFormat = templateResult.formatStr;
    }
  });

  // Handle template input keydown to only allow valid chars
  function handleTemplateKeydown(e: KeyboardEvent, charIndex: number) {
    // Allow navigation keys
    if (['ArrowLeft', 'ArrowRight', 'Tab', 'Backspace', 'Delete'].includes(e.key)) return;
    // Allow valid marker chars and space
    if (![...MARKER_CHARS, ' '].includes(e.key)) {
      e.preventDefault();
    }
  }

  // Handle template input as a whole text input
  function handleTemplateInput(e: Event) {
    const input = e.target as HTMLInputElement;
    const raw = input.value;
    // Pad or trim to filename length
    const len = sampleFilename.length;
    let result = raw.slice(0, len);
    // Replace invalid chars with spaces
    result = result
      .split('')
      .map((ch) => (isMarker(ch) || ch === ' ' ? ch : ' '))
      .join('');
    // Pad with spaces
    while (result.length < len) result += ' ';
    templateString = result;
    input.value = result;
  }

  // ── Mutations ──────────────────────────────────────────────────────────────

  const testMut = createMutation({
    mutationFn: () => {
      if (!activePattern || !activeFormat) throw new Error('No pattern set');
      return testDatetimePattern(projectId, datasetId, activePattern, activeFormat);
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
      return applyDatetimePattern(projectId, datasetId, activePattern, activeFormat);
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
    step = 'manual';
  }

  // Filename cell colors based on whether template has a marker at that position
  function getFilenameCharClass(index: number): string {
    const tch = templateString[index] ?? ' ';
    if (isMarker(tch)) {
      return MARKER_COLORS[tch] ?? '';
    }
    return '';
  }

  function formatParsedDatetime(dt: string | null): string {
    if (!dt) return '-';
    try {
      return new Date(dt).toLocaleString(getLocale());
    } catch {
      return dt;
    }
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
    class="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg bg-white shadow-xl"
    onclick={(e) => e.stopPropagation()}
    role="document"
  >
    <!-- Header -->
    <div class="flex flex-shrink-0 items-center justify-between border-b border-gray-200 px-6 py-4">
      <h3 id="datetime-config-modal-title" class="m-0 text-lg font-semibold text-gray-900">
        {m.datetime_config_modal_title()}
      </h3>
      <button
        type="button"
        onclick={onClose}
        aria-label="Close"
        class="rounded p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
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
        <div class="flex items-center gap-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
          <svg class="h-5 w-5 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          <span class="text-sm text-blue-700">{m.datetime_config_auto_detecting()}</span>
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

          <div class="rounded-md bg-white/60 px-3 py-2 text-xs font-mono text-gray-700 border border-green-200">
            {autoDetectResult.format_str}
          </div>

          <!-- Preview of auto-detect results -->
          {#if autoDetectResult.results.length > 0}
            <div class="overflow-x-auto rounded-md border border-green-200 bg-white">
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
                    <tr class="border-b border-gray-100 last:border-0">
                      <td class="px-3 py-1.5 font-mono text-gray-700">{result.filename}</td>
                      <td class="px-3 py-1.5 text-gray-600">{formatParsedDatetime(result.parsed_datetime)}</td>
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
              class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
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

      <!-- Manual configuration (always shown when step === 'manual') -->
      {#if step === 'manual'}
        <!-- Presets -->
        <div>
          <h4 class="mb-3 text-sm font-semibold text-gray-700">{m.datetime_config_presets_title()}</h4>
          <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {#each PRESETS as preset}
              <button
                type="button"
                onclick={() => applyPreset(preset)}
                class="flex flex-col items-start rounded-lg border border-gray-200 px-3 py-2.5 text-left transition-colors hover:border-blue-300 hover:bg-blue-50 {activeFormat === preset.format && activePattern === preset.pattern ? 'border-blue-400 bg-blue-50' : 'bg-white'}"
              >
                <span class="text-xs font-medium text-gray-900">{preset.name}</span>
                <span class="mt-0.5 font-mono text-xs text-gray-500">{preset.example}</span>
              </button>
            {/each}
          </div>
        </div>

        <!-- Template string UI -->
        {#if sampleFilename}
          <div>
            <h4 class="mb-1 text-sm font-semibold text-gray-700">{m.datetime_config_template_title()}</h4>
            <p class="mb-3 text-xs text-gray-500">{m.datetime_config_template_description()}</p>

            <!-- Color legend -->
            <div class="mb-3 flex flex-wrap gap-2">
              {#each ([['Y', m.datetime_config_year()], ['M', m.datetime_config_month()], ['D', m.datetime_config_day()], ['h', m.datetime_config_hour()], ['m', m.datetime_config_minute()], ['s', m.datetime_config_second()]] as const) as [char, label]}
                <span class="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium {MARKER_COLORS[char] ?? ''}">
                  {char} = {label}
                </span>
              {/each}
            </div>

            <!-- Filename display with per-character coloring -->
            <div class="overflow-x-auto rounded-t-md border border-b-0 border-gray-300 bg-gray-50 px-3 py-2">
              <div class="flex font-mono text-sm leading-relaxed">
                {#each sampleFilename.split('') as char, i}
                  <span
                    class="inline-block min-w-[0.65rem] text-center {getFilenameCharClass(i)} {getFilenameCharClass(i) ? 'rounded-sm' : ''}"
                  >{char}</span>
                {/each}
              </div>
            </div>

            <!-- Editable template row -->
            <div class="overflow-x-auto">
              <input
                type="text"
                class="w-full rounded-b-md border border-gray-300 bg-white px-3 py-2 font-mono text-sm tracking-normal focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
                value={templateString}
                maxlength={sampleFilename.length}
                spellcheck={false}
                oninput={handleTemplateInput}
                aria-label="Datetime template"
              />
            </div>

            <p class="mt-1.5 text-xs text-gray-400">{m.datetime_config_template_help()}</p>

            {#if templateResult}
              <div class="mt-3 rounded-md bg-gray-50 border border-gray-200 px-3 py-2 space-y-1">
                <div class="flex items-center gap-2 text-xs">
                  <span class="font-medium text-gray-500">Pattern:</span>
                  <code class="font-mono text-gray-700">{templateResult.pattern}</code>
                </div>
                <div class="flex items-center gap-2 text-xs">
                  <span class="font-medium text-gray-500">Format:</span>
                  <code class="font-mono text-gray-700">{templateResult.formatStr}</code>
                </div>
              </div>
            {/if}
          </div>
        {:else}
          <div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-6 text-center text-sm text-gray-500">
            {m.datetime_config_no_recordings()}
          </div>
        {/if}

        <!-- Test / Preview section -->
        {#if activePattern && activeFormat}
          <div>
            <div class="flex items-center justify-between mb-3">
              <h4 class="text-sm font-semibold text-gray-700">{m.datetime_config_preview_title()}</h4>
              <button
                type="button"
                onclick={() => $testMut.mutate()}
                disabled={$testMut.isPending}
                class="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
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
              <div class="overflow-x-auto rounded-md border border-gray-200">
                <table class="w-full text-xs">
                  <thead>
                    <tr class="border-b border-gray-200 bg-gray-50">
                      <th class="px-3 py-2 text-left font-medium text-gray-600">{m.datetime_config_preview_filename()}</th>
                      <th class="px-3 py-2 text-left font-medium text-gray-600">{m.datetime_config_preview_datetime()}</th>
                      <th class="w-12 px-3 py-2 text-center font-medium text-gray-600">{m.datetime_config_preview_status()}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each previewResults as result}
                      <tr class="border-b border-gray-100 last:border-0 {result.success ? '' : 'bg-red-50'}">
                        <td class="px-3 py-1.5 font-mono text-gray-700">{result.filename}</td>
                        <td class="px-3 py-1.5 text-gray-600">
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
    <div class="flex flex-shrink-0 items-center justify-between gap-3 rounded-b-lg border-t border-gray-200 bg-gray-50 px-6 py-4">
      <button
        type="button"
        onclick={onClose}
        class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
      >
        {m.common_cancel()}
      </button>

      {#if step === 'manual' && activePattern && activeFormat}
        <button
          type="button"
          onclick={() => $applyMut.mutate()}
          disabled={$applyMut.isPending}
          class="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
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
