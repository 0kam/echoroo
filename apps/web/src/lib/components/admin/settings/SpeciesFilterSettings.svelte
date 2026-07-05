<script lang="ts">
  /**
   * Detection settings card (BirdNET species filter + minimum confidence)
   * for the admin system-settings form.
   *
   * Presentational: two-way binds the detection form fields and reads
   * last-updated timestamps from the loaded settings map.
   */

  import type { SystemSetting } from '$lib/api/admin';
  import type { BirdnetSpeciesFilter } from '$lib/types';
  import * as m from '$lib/paraglide/messages';

  let {
    settings,
    birdnetSpeciesFilter = $bindable(),
    birdnetMinConf = $bindable(),
    formatDate,
  }: {
    settings: Record<string, SystemSetting>;
    birdnetSpeciesFilter: BirdnetSpeciesFilter;
    birdnetMinConf: number;
    formatDate: (dateString: string) => string;
  } = $props();

  /**
   * Handle BirdNET species filter change
   */
  function handleSpeciesFilterChange(event: Event) {
    const target = event.target as HTMLSelectElement;
    birdnetSpeciesFilter = target.value as BirdnetSpeciesFilter;
  }

  /**
   * Handle BirdNET min confidence change
   */
  function handleMinConfChange(event: Event) {
    const target = event.target as HTMLInputElement;
    birdnetMinConf = parseFloat(target.value);
  }
</script>

<!-- Detection Settings Card -->
<div class="overflow-hidden rounded-lg bg-surface-card shadow">
  <div class="border-b border-stone-200 px-6 py-4">
    <h2 class="text-lg font-medium text-stone-900">{m.admin_settings_detection_heading()}</h2>
    <p class="mt-1 text-sm text-stone-500">{m.admin_settings_detection_description()}</p>
  </div>

  <div class="space-y-6 px-6 py-5">
    <!-- Species Filter -->
    <div>
      <label for="species-filter" class="block text-sm font-medium text-stone-700">
        {m.admin_settings_detection_species_filter_label()}
      </label>
      <select
        id="species-filter"
        value={birdnetSpeciesFilter}
        onchange={handleSpeciesFilterChange}
        class="mt-1 block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 sm:text-sm"
      >
        <option value="none">{m.admin_settings_detection_species_filter_none()}</option>
        <option value="birdnet_geo">{m.admin_settings_detection_species_filter_birdnet_geo()}</option>
      </select>
      <p class="mt-2 text-sm text-stone-500">
        {m.admin_settings_detection_species_filter_hint()}
      </p>
      {#if settings.birdnet_species_filter?.updated_at}
        <p class="mt-1 text-xs text-stone-400">
          {m.admin_settings_last_updated({ date: formatDate(settings.birdnet_species_filter.updated_at) })}
        </p>
      {/if}
    </div>

    <!-- Min Confidence -->
    <div>
      <label for="min-confidence" class="block text-sm font-medium text-stone-700">
        {m.admin_settings_detection_min_conf_label()}
      </label>
      <input
        type="number"
        id="min-confidence"
        value={birdnetMinConf}
        oninput={handleMinConfChange}
        min="0"
        max="1"
        step="0.01"
        class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 sm:text-sm"
      />
      <p class="mt-2 text-sm text-stone-500">
        {m.admin_settings_detection_min_conf_hint()}
      </p>
      {#if settings.birdnet_min_conf?.updated_at}
        <p class="mt-1 text-xs text-stone-400">
          {m.admin_settings_last_updated({ date: formatDate(settings.birdnet_min_conf.updated_at) })}
        </p>
      {/if}
    </div>
  </div>
</div>
