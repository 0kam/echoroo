<script lang="ts">
  /**
   * Admin - System Settings Page
   */

  import { adminApi } from '$lib/api/admin';
  import type { SystemSetting } from '$lib/api/admin';
  import type { BirdnetSpeciesFilter } from '$lib/types';
  import { ApiError } from '$lib/api/client';
  import { getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import RegistrationSettings from '$lib/components/admin/settings/RegistrationSettings.svelte';
  import SpeciesFilterSettings from '$lib/components/admin/settings/SpeciesFilterSettings.svelte';
  import BirdnetSeedPanel from '$lib/components/admin/settings/BirdnetSeedPanel.svelte';
  import VernacularSyncPanel from '$lib/components/admin/settings/VernacularSyncPanel.svelte';

  // State
  let settings = $state<Record<string, SystemSetting>>({});
  let isLoading = $state(true);
  let isSaving = $state(false);
  let error = $state<string | null>(null);
  let successMessage = $state<string | null>(null);

  // Form state - registration
  let registrationMode = $state<'open' | 'invitation'>('open');
  let allowRegistration = $state(true);
  // Form state - session
  let sessionTimeoutMinutes = $state(60);
  // Form state - detection
  let birdnetSpeciesFilter = $state<BirdnetSpeciesFilter>('none');
  let birdnetMinConf = $state(0.25);

  // Taxon maintenance state.
  // These dispatch background Celery tasks via the superuser BFF endpoints
  // (mirrors the IUCN force-resync dispatch contract). Buttons are disabled
  // while a dispatch is in flight; results surface through the same shared
  // success/error banners as the settings form.
  let isSeedingBirdnet = $state(false);
  let isSyncingVernacular = $state(false);
  // Sync vernacular form inputs.
  let vernacularBatchSize = $state(100);
  let vernacularLocales = $state('ja');
  let vernacularSkipExisting = $state(true);

  /**
   * Load system settings
   */
  async function loadSettings() {
    isLoading = true;
    error = null;

    try {
      settings = await adminApi.getSystemSettings();

      // Populate form fields from settings
      if (settings.registration_mode) {
        registrationMode = settings.registration_mode.value as 'open' | 'invitation';
      }
      if (settings.allow_registration) {
        allowRegistration = settings.allow_registration.value as boolean;
      }
      if (settings.session_timeout_minutes) {
        sessionTimeoutMinutes = settings.session_timeout_minutes.value as number;
      }
      if (settings.birdnet_species_filter) {
        birdnetSpeciesFilter = settings.birdnet_species_filter.value as BirdnetSpeciesFilter;
      }
      if (settings.birdnet_min_conf) {
        birdnetMinConf = settings.birdnet_min_conf.value as number;
      }
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.admin_settings_error_load();
      }
    } finally {
      isLoading = false;
    }
  }

  // Load settings on mount
  $effect(() => {
    loadSettings();
  });

  /**
   * Save settings
   */
  async function handleSave(event: Event) {
    event.preventDefault();

    isSaving = true;
    error = null;
    successMessage = null;

    try {
      await adminApi.updateSystemSettings({
        registration_mode: registrationMode,
        allow_registration: allowRegistration,
        session_timeout_minutes: sessionTimeoutMinutes,
        birdnet_species_filter: birdnetSpeciesFilter,
        birdnet_min_conf: birdnetMinConf,
      });

      successMessage = m.admin_settings_success();

      // Reload settings to get updated values
      await loadSettings();

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.admin_settings_error_save();
      }
    } finally {
      isSaving = false;
    }
  }

  /**
   * Dispatch the BirdNET taxon seed task after confirmation.
   */
  async function handleSeedBirdnet() {
    isSeedingBirdnet = true;
    error = null;
    successMessage = null;

    try {
      const result = await adminApi.seedBirdnetTaxa();
      successMessage = m.admin_settings_taxon_seed_birdnet_success({ taskId: result.task_id });

      setTimeout(() => {
        successMessage = null;
      }, 5000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.admin_settings_taxon_seed_birdnet_error();
      }
    } finally {
      isSeedingBirdnet = false;
    }
  }

  /**
   * Dispatch the vernacular-name sync task after confirmation.
   *
   * The free-text locales input is split on commas into a trimmed list;
   * an empty input is sent as `null` so the backend syncs all configured
   * locales.
   */
  async function handleSyncVernacular() {
    isSyncingVernacular = true;
    error = null;
    successMessage = null;

    const locales = vernacularLocales
      .split(',')
      .map((value) => value.trim())
      .filter((value) => value.length > 0);

    try {
      const result = await adminApi.syncVernacularNames({
        batch_size: vernacularBatchSize,
        locales: locales.length > 0 ? locales : null,
        skip_existing: vernacularSkipExisting,
      });
      successMessage = m.admin_settings_taxon_sync_vernacular_success({ taskId: result.task_id });

      setTimeout(() => {
        successMessage = null;
      }, 5000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.admin_settings_taxon_sync_vernacular_error();
      }
    } finally {
      isSyncingVernacular = false;
    }
  }

  /**
   * Format date
   */
  function formatDate(dateString: string): string {
    return new Date(dateString).toLocaleString(getLocale());
  }
</script>

<svelte:head>
  <title>{m.admin_settings_page_title()}</title>
</svelte:head>

<div class="px-8 py-6">
  <!-- Header -->
  <div class="mb-6">
    <h1 class="text-3xl font-bold text-stone-900">{m.admin_settings_heading()}</h1>
    <p class="mt-2 text-sm text-stone-600">{m.admin_settings_description()}</p>
  </div>

  <!-- Success Message -->
  {#if successMessage}
    <div class="mb-6 rounded-md bg-success-light p-4" role="alert">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg
            class="h-5 w-5 text-success"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fill-rule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
              clip-rule="evenodd"
            />
          </svg>
        </div>
        <div class="ml-3">
          <p class="text-sm font-medium text-success">{successMessage}</p>
        </div>
      </div>
    </div>
  {/if}

  <!-- Error Message -->
  {#if error}
    <div class="mb-6 rounded-md bg-danger-light p-4" role="alert">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg
            class="h-5 w-5 text-danger"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fill-rule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
              clip-rule="evenodd"
            />
          </svg>
        </div>
        <div class="ml-3">
          <p class="text-sm font-medium text-danger">{error}</p>
        </div>
      </div>
    </div>
  {/if}

  {#if isLoading}
    <!-- Loading State -->
    <div class="flex items-center justify-center py-12">
      <svg
        class="h-8 w-8 animate-spin text-primary-600"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
        ></circle>
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        ></path>
      </svg>
    </div>
  {:else}
    <!-- Settings Form -->
    <form onsubmit={handleSave} class="space-y-6">
      <RegistrationSettings
        {settings}
        bind:registrationMode
        bind:allowRegistration
        bind:sessionTimeoutMinutes
        {formatDate}
      />

      <SpeciesFilterSettings
        {settings}
        bind:birdnetSpeciesFilter
        bind:birdnetMinConf
        {formatDate}
      />

      <!-- Taxon Maintenance Card -->
      <div class="overflow-hidden rounded-lg bg-surface-card shadow">
        <div class="border-b border-stone-200 px-6 py-4">
          <h2 class="text-lg font-medium text-stone-900">{m.admin_settings_taxon_heading()}</h2>
          <p class="mt-1 text-sm text-stone-500">{m.admin_settings_taxon_description()}</p>
        </div>

        <div class="space-y-8 px-6 py-5">
          <BirdnetSeedPanel isSeeding={isSeedingBirdnet} onSeed={handleSeedBirdnet} />

          <VernacularSyncPanel
            isSyncing={isSyncingVernacular}
            onSync={handleSyncVernacular}
            bind:vernacularBatchSize
            bind:vernacularLocales
            bind:vernacularSkipExisting
          />
        </div>
      </div>

      <!-- Form Actions -->
      <div class="flex justify-end space-x-3">
        <button
          type="button"
          onclick={() => loadSettings()}
          disabled={isSaving}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 shadow-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.admin_settings_reset()}
        </button>
        <button
          type="submit"
          disabled={isSaving}
          class="inline-flex items-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
        >
          {#if isSaving}
            <svg
              class="mr-2 h-4 w-4 animate-spin"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                class="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                stroke-width="4"
              ></circle>
              <path
                class="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              ></path>
            </svg>
            {m.admin_settings_saving()}
          {:else}
            {m.admin_settings_save()}
          {/if}
        </button>
      </div>
    </form>
  {/if}
</div>
