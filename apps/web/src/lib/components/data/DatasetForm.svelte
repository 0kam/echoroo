<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { fetchSites } from '$lib/api/sites';
  import { fetchRecorders } from '$lib/api/recorders';
  import DatetimePatternTester from './DatetimePatternTester.svelte';
  import VisibilitySelector from './VisibilitySelector.svelte';
  import type { DatasetCreate, DatasetDetail, DatasetUpdate, DatasetVisibility } from '$lib/types/data';

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
      error = 'Name is required';
      return;
    }
    if (!isEdit && !siteId) {
      error = 'Site is required';
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
        };
        await onSubmit(createData);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to save dataset';
    } finally {
      isSubmitting = false;
    }
  }
</script>

<form class="flex flex-col gap-5" onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
  <!-- Name -->
  <div class="flex flex-col gap-1.5">
    <label for="name" class="text-sm font-medium text-gray-700">Name *</label>
    <input
      id="name"
      type="text"
      bind:value={name}
      placeholder="Enter dataset name"
      maxlength="200"
      required
      class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
    />
  </div>

  <!-- Description -->
  <div class="flex flex-col gap-1.5">
    <label for="description" class="text-sm font-medium text-gray-700">Description</label>
    <textarea
      id="description"
      bind:value={description}
      placeholder="Describe this dataset"
      rows="3"
      class="resize-y rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
    ></textarea>
  </div>

  <!-- Site + Visibility row -->
  <div class="grid grid-cols-2 gap-4">
    <div class="flex flex-col gap-1.5">
      <label for="site" class="text-sm font-medium text-gray-700">Site *</label>
      {#if $sitesQuery.isLoading}
        <select id="site" disabled class="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm">
          <option>Loading sites...</option>
        </select>
      {:else if $sitesQuery.isError}
        <div class="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">Error loading sites</div>
      {:else if $sitesQuery.data}
        <select
          id="site"
          bind:value={siteId}
          required={!isEdit}
          disabled={isEdit}
          class="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-500"
        >
          <option value="">Select a site</option>
          {#each $sitesQuery.data.items as site}
            <option value={site.id}>{site.name}</option>
          {/each}
        </select>
        {#if isEdit}
          <p class="text-xs text-gray-400">Site cannot be changed after creation</p>
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
  <details open class="rounded-md border border-gray-200 bg-gray-50 p-4">
    <summary class="cursor-pointer select-none text-sm font-medium text-gray-700 hover:text-blue-600">
      Advanced Options
    </summary>

    <div class="mt-4 flex flex-col gap-4">
      <div class="grid grid-cols-2 gap-4">
        <div class="flex flex-col gap-1.5">
          <label for="recorder" class="text-sm font-medium text-gray-700">Recorder</label>
          {#if $recordersQuery.isLoading}
            <select id="recorder" disabled class="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm">
              <option>Loading recorders...</option>
            </select>
          {:else if $recordersQuery.isError}
            <div class="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">Error loading recorders</div>
          {:else if $recordersQuery.data}
            <select
              id="recorder"
              bind:value={recorderId}
              class="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            >
              <option value="">No recorder</option>
              {#each $recordersQuery.data.items as recorder}
                <option value={recorder.id}>{recorder.manufacturer} {recorder.recorder_name}</option>
              {/each}
            </select>
          {/if}
          <p class="text-xs text-gray-400">Recording device used for this dataset</p>
        </div>

        <div class="flex flex-col gap-1.5">
          <label for="license" class="text-sm font-medium text-gray-700">License</label>
          <input
            id="license"
            type="text"
            bind:value={licenseId}
            placeholder="License ID (optional)"
            class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
          <p class="text-xs text-gray-400">Data license identifier</p>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div class="flex flex-col gap-1.5">
          <label for="doi" class="text-sm font-medium text-gray-700">DOI</label>
          <input
            id="doi"
            type="text"
            bind:value={doi}
            placeholder="10.xxxx/xxxxx (optional)"
            class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>

        <div class="flex flex-col gap-1.5">
          <label for="gain" class="text-sm font-medium text-gray-700">Gain (dB)</label>
          <input
            id="gain"
            type="number"
            step="0.1"
            bind:value={gain}
            placeholder="0.0"
            class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
      </div>

      <div class="flex flex-col gap-1.5">
        <label for="note" class="text-sm font-medium text-gray-700">Note</label>
        <textarea
          id="note"
          bind:value={note}
          placeholder="Additional notes"
          rows="2"
          class="resize-y rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        ></textarea>
      </div>

      <!-- Datetime extraction (edit mode only) -->
      {#if isEdit}
        <div class="border-t border-gray-200 pt-4">
          <h4 class="mb-1 text-sm font-semibold text-gray-700">Datetime Extraction (Optional)</h4>
          <p class="mb-3 text-xs text-gray-500">
            Configure how to extract recording datetime from filenames. If not provided, file modification time will be used.
          </p>

          <div class="grid grid-cols-2 gap-4">
            <div class="flex flex-col gap-1.5">
              <label for="datetime-pattern" class="text-sm font-medium text-gray-700">Regex Pattern</label>
              <input
                id="datetime-pattern"
                type="text"
                bind:value={datetimePattern}
                placeholder="e.g., (\d{8}_\d{6})"
                class="rounded-md border border-gray-300 px-3 py-2 font-mono text-sm focus:border-blue-500 focus:outline-none"
              />
              <p class="text-xs text-gray-400">Regular expression to extract datetime from filename</p>
            </div>

            <div class="flex flex-col gap-1.5">
              <label for="datetime-format" class="text-sm font-medium text-gray-700">Datetime Format</label>
              <input
                id="datetime-format"
                type="text"
                bind:value={datetimeFormat}
                placeholder="e.g., %Y%m%d_%H%M%S"
                class="rounded-md border border-gray-300 px-3 py-2 font-mono text-sm focus:border-blue-500 focus:outline-none"
              />
              <p class="text-xs text-gray-400">Python strptime format for parsing</p>
            </div>
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
    <div class="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
      {error}
    </div>
  {/if}

  <div class="flex justify-end gap-3 border-t border-gray-200 pt-4">
    <button
      type="button"
      onclick={onCancel}
      disabled={isSubmitting}
      class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
    >
      Cancel
    </button>
    <button
      type="submit"
      disabled={isSubmitting || !name || (!isEdit && !siteId)}
      class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {isSubmitting ? 'Saving...' : isEdit ? 'Update Dataset' : 'Create Dataset'}
    </button>
  </div>
</form>
