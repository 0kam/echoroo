<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { fetchSites } from '$lib/api/sites';
  import { fetchRecorders } from '$lib/api/recorders';
  import DatetimePatternTester from './DatetimePatternTester.svelte';
  import VisibilitySelector from './VisibilitySelector.svelte';
  import type { DatasetCreate, DatasetDetail, DatasetUpdate, DatasetVisibility } from '$lib/types/data';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    projectId: string;
    dataset?: DatasetDetail | null;
    onSubmit: (data: DatasetCreate | DatasetUpdate) => Promise<void>;
    onCancel?: () => void;
  }

  let { projectId, dataset = null, onSubmit, onCancel = () => {} }: Props = $props();

  const isEdit = $derived(!!dataset);

  // Form fields (initialized from dataset prop)
  let name = $state('');
  let description = $state('');
  let visibility = $state<DatasetVisibility>('private');
  let siteId = $state('');
  let recorderId = $state('');
  let licenseId = $state('');
  let doi = $state('');
  let gain = $state('');
  let note = $state('');
  let datetimePattern = $state('');
  let datetimeFormat = $state('');
  let datetimeTimezone = $state('');

  // Initialize form fields from dataset prop once on mount
  $effect(() => {
    name = dataset?.name ?? '';
    description = dataset?.description ?? '';
    visibility = dataset?.visibility ?? 'private';
    siteId = dataset?.site_id ?? '';
    recorderId = dataset?.recorder_id ?? '';
    licenseId = dataset?.license_id ?? '';
    doi = dataset?.doi ?? '';
    gain = dataset?.gain?.toString() ?? '';
    note = dataset?.note ?? '';
    datetimeTimezone = dataset?.datetime_timezone ?? '';
  });

  let isSubmitting = $state(false);
  let error = $state('');

  // Fetch sites for dropdown
  const sitesQuery = $derived(
    createQuery({
      queryKey: ['sites', projectId],
      queryFn: () => fetchSites(projectId, { page_size: 100 }),
    })
  );

  // Fetch recorders for dropdown
  const recordersQuery = $derived(
    createQuery({
      queryKey: ['recorders'],
      queryFn: () => fetchRecorders({ limit: 100 }),
    })
  );

  async function handleSubmit() {
    // Validation
    if (!name.trim()) {
      error = m.validation_name_required();
      return;
    }
    if (!isEdit && !siteId) {
      error = m.validation_site_required();
      return;
    }

    error = '';
    isSubmitting = true;

    try {
      if (isEdit) {
        const updateData: DatasetUpdate = {
          name: name.trim(),
          description: description.trim() || null,
          visibility,
          recorder_id: recorderId || null,
          license_id: licenseId || null,
          doi: doi.trim() || null,
          gain: gain ? parseFloat(gain) : null,
          note: note.trim() || null,
          datetime_pattern: datetimePattern.trim() || null,
          datetime_format: datetimeFormat.trim() || null,
          datetime_timezone: datetimeTimezone || null,
        };
        await onSubmit(updateData);
      } else {
        const createData: DatasetCreate = {
          site_id: siteId,
          name: name.trim(),
          description: description.trim() || null,
          visibility,
          recorder_id: recorderId || null,
          license_id: licenseId || null,
          doi: doi.trim() || null,
          gain: gain ? parseFloat(gain) : null,
          note: note.trim() || null,
          datetime_pattern: datetimePattern.trim() || null,
          datetime_format: datetimeFormat.trim() || null,
          datetime_timezone: datetimeTimezone || null,
        };
        await onSubmit(createData);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : m.error_save_dataset();
    } finally {
      isSubmitting = false;
    }
  }
</script>

<form class="flex flex-col gap-5" onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
  <!-- Name -->
  <div class="flex flex-col gap-1.5">
    <label for="name" class="text-sm font-medium text-stone-700">{m.form_dataset_name_label()} *</label>
    <input
      id="name"
      type="text"
      bind:value={name}
      placeholder={m.form_dataset_name_placeholder()}
      maxlength="200"
      required
      class="rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
    />
  </div>

  <!-- Description -->
  <div class="flex flex-col gap-1.5">
    <label for="description" class="text-sm font-medium text-stone-700">{m.form_dataset_description_label()}</label>
    <textarea
      id="description"
      bind:value={description}
      placeholder={m.form_dataset_description_placeholder()}
      rows="3"
      class="resize-y rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
    ></textarea>
  </div>

  <!-- Site + Visibility row -->
  <div class="grid grid-cols-2 gap-4">
    <div class="flex flex-col gap-1.5">
      <label for="site" class="text-sm font-medium text-stone-700">{m.form_dataset_site_label()} *</label>
      {#if $sitesQuery.isLoading}
        <select id="site" disabled class="rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm">
          <option>{m.common_loading_sites()}</option>
        </select>
      {:else if $sitesQuery.isError}
        <div class="rounded-md border border-danger/20 bg-danger-light px-3 py-2 text-sm text-danger">{m.common_error_load_sites()}</div>
      {:else if $sitesQuery.data}
        <select
          id="site"
          bind:value={siteId}
          required={!isEdit}
          disabled={isEdit}
          class="rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm focus:border-primary-500 focus:outline-none disabled:bg-stone-50 disabled:text-stone-500"
        >
          <option value="">{m.form_dataset_site_select_placeholder()}</option>
          {#each $sitesQuery.data.items as site}
            <option value={site.id}>{site.name}</option>
          {/each}
        </select>
        {#if isEdit}
          <p class="text-xs text-stone-400">{m.form_dataset_site_cannot_change()}</p>
        {/if}
      {/if}
    </div>

    <div class="flex flex-col gap-1.5">
      <VisibilitySelector
        value={visibility}
        onChange={(v) => (visibility = v)}
      />
    </div>
  </div>

  <!-- Advanced options -->
  <details open class="rounded-md border border-stone-200 bg-stone-50 p-4">
    <summary class="cursor-pointer select-none text-sm font-medium text-stone-700 hover:text-primary-600">
      Advanced Options
    </summary>

    <div class="mt-4 flex flex-col gap-4">
      <div class="grid grid-cols-2 gap-4">
        <div class="flex flex-col gap-1.5">
          <label for="recorder" class="text-sm font-medium text-stone-700">{m.form_dataset_recorder_label()}</label>
          {#if $recordersQuery.isLoading}
            <select id="recorder" disabled class="rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm">
              <option>{m.common_loading_recorders()}</option>
            </select>
          {:else if $recordersQuery.isError}
            <div class="rounded-md border border-danger/20 bg-danger-light px-3 py-2 text-sm text-danger">{m.common_error_load_recorders()}</div>
          {:else if $recordersQuery.data}
            <select
              id="recorder"
              bind:value={recorderId}
              class="rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
            >
              <option value="">{m.form_dataset_recorder_none()}</option>
              {#each $recordersQuery.data.items as recorder}
                <option value={recorder.id}>{recorder.manufacturer} {recorder.recorder_name}</option>
              {/each}
            </select>
          {/if}
          <p class="text-xs text-stone-400">{m.form_dataset_recorder_hint()}</p>
        </div>

        <div class="flex flex-col gap-1.5">
          <label for="license" class="text-sm font-medium text-stone-700">License</label>
          <input
            id="license"
            type="text"
            bind:value={licenseId}
            placeholder="License ID (optional)"
            class="rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
          />
          <p class="text-xs text-stone-400">Data license identifier</p>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div class="flex flex-col gap-1.5">
          <label for="doi" class="text-sm font-medium text-stone-700">DOI</label>
          <input
            id="doi"
            type="text"
            bind:value={doi}
            placeholder="10.xxxx/xxxxx (optional)"
            class="rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
          />
        </div>

        <div class="flex flex-col gap-1.5">
          <label for="gain" class="text-sm font-medium text-stone-700">Gain (dB)</label>
          <input
            id="gain"
            type="number"
            step="0.1"
            bind:value={gain}
            placeholder="0.0"
            class="rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
          />
        </div>
      </div>

      <div class="flex flex-col gap-1.5">
        <label for="note" class="text-sm font-medium text-stone-700">Note</label>
        <textarea
          id="note"
          bind:value={note}
          placeholder="Additional notes"
          rows="2"
          class="resize-y rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
        ></textarea>
      </div>

      <!-- Datetime extraction (edit mode only) -->
      {#if isEdit}
        <div class="border-t border-stone-200 pt-4">
          <h4 class="mb-1 text-sm font-semibold text-stone-700">Datetime Extraction (Optional)</h4>
          <p class="mb-3 text-xs text-stone-500">
            Configure how to extract recording datetime from filenames. If not provided, file modification time will be used.
          </p>

          <div class="grid grid-cols-2 gap-4">
            <div class="flex flex-col gap-1.5">
              <label for="datetime-pattern" class="text-sm font-medium text-stone-700">Regex Pattern</label>
              <input
                id="datetime-pattern"
                type="text"
                bind:value={datetimePattern}
                placeholder="e.g., (\d{8}_\d{6})"
                class="rounded-md border border-stone-300 px-3 py-2 font-mono text-sm focus:border-primary-500 focus:outline-none"
              />
              <p class="text-xs text-stone-400">Regular expression to extract datetime from filename</p>
            </div>

            <div class="flex flex-col gap-1.5">
              <label for="datetime-format" class="text-sm font-medium text-stone-700">Datetime Format</label>
              <input
                id="datetime-format"
                type="text"
                bind:value={datetimeFormat}
                placeholder="e.g., %Y%m%d_%H%M%S"
                class="rounded-md border border-stone-300 px-3 py-2 font-mono text-sm focus:border-primary-500 focus:outline-none"
              />
              <p class="text-xs text-stone-400">Python strptime format for parsing</p>
            </div>
          </div>

          <div class="flex flex-col gap-1.5">
            <label for="datetime-timezone" class="text-sm font-medium text-stone-700">{m.datetime_config_timezone_label()}</label>
            <select
              id="datetime-timezone"
              bind:value={datetimeTimezone}
              class="rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            >
              <option value="">{m.datetime_config_timezone_none()}</option>
              <optgroup label="UTC">
                <option value="UTC">UTC</option>
              </optgroup>
              <optgroup label="Asia">
                <option value="Asia/Tokyo">Asia/Tokyo (JST, UTC+9)</option>
                <option value="Asia/Shanghai">Asia/Shanghai (CST, UTC+8)</option>
                <option value="Asia/Singapore">Asia/Singapore (SGT, UTC+8)</option>
                <option value="Asia/Kolkata">Asia/Kolkata (IST, UTC+5:30)</option>
                <option value="Asia/Dubai">Asia/Dubai (GST, UTC+4)</option>
              </optgroup>
              <optgroup label="Australia / Pacific">
                <option value="Australia/Sydney">Australia/Sydney (AEST/AEDT)</option>
                <option value="Australia/Perth">Australia/Perth (AWST, UTC+8)</option>
                <option value="Pacific/Auckland">Pacific/Auckland (NZST/NZDT)</option>
              </optgroup>
              <optgroup label="Europe">
                <option value="Europe/London">Europe/London (GMT/BST)</option>
                <option value="Europe/Paris">Europe/Paris (CET/CEST)</option>
                <option value="Europe/Berlin">Europe/Berlin (CET/CEST)</option>
                <option value="Europe/Helsinki">Europe/Helsinki (EET/EEST)</option>
              </optgroup>
              <optgroup label="America">
                <option value="America/New_York">America/New_York (EST/EDT)</option>
                <option value="America/Chicago">America/Chicago (CST/CDT)</option>
                <option value="America/Denver">America/Denver (MST/MDT)</option>
                <option value="America/Los_Angeles">America/Los_Angeles (PST/PDT)</option>
                <option value="America/Anchorage">America/Anchorage (AKST/AKDT)</option>
                <option value="America/Sao_Paulo">America/Sao_Paulo (BRT)</option>
              </optgroup>
              <optgroup label="Africa">
                <option value="Africa/Nairobi">Africa/Nairobi (EAT, UTC+3)</option>
                <option value="Africa/Johannesburg">Africa/Johannesburg (SAST, UTC+2)</option>
              </optgroup>
            </select>
            <p class="text-xs text-stone-400">{m.datetime_config_timezone_hint()}</p>
          </div>

          {#if datetimePattern || datetimeFormat}
            <div class="mt-3">
              <DatetimePatternTester pattern={datetimePattern} format={datetimeFormat} />
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </details>

  {#if error}
    <div class="rounded-md border border-danger/20 bg-danger-light px-3 py-2 text-sm text-danger">
      {error}
    </div>
  {/if}

  <div class="flex justify-end gap-3 border-t border-stone-200 pt-4">
    <button
      type="button"
      onclick={onCancel}
      disabled={isSubmitting}
      class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {m.form_dataset_cancel()}
    </button>
    <button
      type="submit"
      disabled={isSubmitting || !name || (!isEdit && !siteId)}
      class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
    >
      {isSubmitting ? m.form_dataset_saving() : isEdit ? m.form_dataset_update() : m.form_dataset_create()}
    </button>
  </div>
</form>
