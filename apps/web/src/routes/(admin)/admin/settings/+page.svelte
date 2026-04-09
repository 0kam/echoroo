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
   * Handle registration mode change
   */
  function handleRegistrationModeChange(event: Event) {
    const target = event.target as HTMLSelectElement;
    registrationMode = target.value as 'open' | 'invitation';
  }

  /**
   * Handle allow registration toggle
   */
  function handleAllowRegistrationToggle() {
    allowRegistration = !allowRegistration;
  }

  /**
   * Handle session timeout change
   */
  function handleSessionTimeoutChange(event: Event) {
    const target = event.target as HTMLInputElement;
    sessionTimeoutMinutes = parseInt(target.value, 10);
  }

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
      <!-- Registration Settings Card -->
      <div class="overflow-hidden rounded-lg bg-surface-card shadow">
        <div class="border-b border-stone-200 px-6 py-4">
          <h2 class="text-lg font-medium text-stone-900">{m.admin_settings_registration_heading()}</h2>
          <p class="mt-1 text-sm text-stone-500">
            {m.admin_settings_registration_description()}
          </p>
        </div>

        <div class="space-y-6 px-6 py-5">
          <!-- Registration Mode -->
          <div>
            <label for="registration-mode" class="block text-sm font-medium text-stone-700">
              {m.admin_settings_registration_mode_label()}
            </label>
            <select
              id="registration-mode"
              value={registrationMode}
              onchange={handleRegistrationModeChange}
              class="mt-1 block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 sm:text-sm"
            >
              <option value="open">{m.admin_settings_registration_mode_open()}</option>
              <option value="invitation">{m.admin_settings_registration_mode_invitation()}</option>
            </select>
            {#if settings.registration_mode?.description}
              <p class="mt-2 text-sm text-stone-500">{settings.registration_mode.description}</p>
            {/if}
            {#if settings.registration_mode?.updated_at}
              <p class="mt-1 text-xs text-stone-400">
                {m.admin_settings_last_updated({ date: formatDate(settings.registration_mode.updated_at) })}
              </p>
            {/if}
          </div>

          <!-- Allow Registration -->
          <div>
            <div class="flex items-center justify-between">
              <div class="flex-1">
                <label for="allow-registration" class="block text-sm font-medium text-stone-700">
                  {m.admin_settings_allow_registration_label()}
                </label>
                <p class="text-sm text-stone-500">{m.admin_settings_allow_registration_description()}</p>
                {#if settings.allow_registration?.updated_at}
                  <p class="mt-1 text-xs text-stone-400">
                    {m.admin_settings_last_updated({ date: formatDate(settings.allow_registration.updated_at) })}
                  </p>
                {/if}
              </div>
              <button
                type="button"
                id="allow-registration"
                onclick={handleAllowRegistrationToggle}
                class="relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 {allowRegistration
                  ? 'bg-primary-600'
                  : 'bg-stone-200'}"
                role="switch"
                aria-checked={allowRegistration}
              >
                <span class="sr-only">{m.admin_settings_allow_registration_sr()}</span>
                <span
                  aria-hidden="true"
                  class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-surface-card shadow ring-0 transition duration-200 ease-in-out {allowRegistration
                    ? 'translate-x-5'
                    : 'translate-x-0'}"
                ></span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Session Settings Card -->
      <div class="overflow-hidden rounded-lg bg-surface-card shadow">
        <div class="border-b border-stone-200 px-6 py-4">
          <h2 class="text-lg font-medium text-stone-900">{m.admin_settings_session_heading()}</h2>
          <p class="mt-1 text-sm text-stone-500">{m.admin_settings_session_description()}</p>
        </div>

        <div class="space-y-6 px-6 py-5">
          <!-- Session Timeout -->
          <div>
            <label for="session-timeout" class="block text-sm font-medium text-stone-700">
              {m.admin_settings_session_timeout_label()}
            </label>
            <input
              type="number"
              id="session-timeout"
              value={sessionTimeoutMinutes}
              oninput={handleSessionTimeoutChange}
              min="1"
              max="10080"
              class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 sm:text-sm"
            />
            <p class="mt-2 text-sm text-stone-500">
              {m.admin_settings_session_timeout_hint()}
            </p>
            {#if settings.session_timeout_minutes?.updated_at}
              <p class="mt-1 text-xs text-stone-400">
                {m.admin_settings_last_updated({ date: formatDate(settings.session_timeout_minutes.updated_at) })}
              </p>
            {/if}
          </div>
        </div>
      </div>

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
          class="inline-flex items-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
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
