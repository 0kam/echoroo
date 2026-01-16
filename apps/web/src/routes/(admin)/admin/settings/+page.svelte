<script lang="ts">
  /**
   * Admin - System Settings Page
   */

  import { adminApi } from '$lib/api/admin';
  import type { SystemSetting } from '$lib/api/admin';
  import { ApiError } from '$lib/api/client';

  // State
  let settings = $state<Record<string, SystemSetting>>({});
  let isLoading = $state(true);
  let isSaving = $state(false);
  let error = $state<string | null>(null);
  let successMessage = $state<string | null>(null);

  // Form state
  let registrationMode = $state<'open' | 'invitation'>('open');
  let allowRegistration = $state(true);
  let sessionTimeoutMinutes = $state(60);

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
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to load system settings';
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
      });

      successMessage = 'Settings saved successfully';

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
        error = 'Failed to save settings';
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
   * Format date
   */
  function formatDate(dateString: string): string {
    return new Date(dateString).toLocaleString();
  }
</script>

<svelte:head>
  <title>System Settings - Admin - Echoroo</title>
</svelte:head>

<div class="px-8 py-6">
  <!-- Header -->
  <div class="mb-6">
    <h1 class="text-3xl font-bold text-gray-900">System Settings</h1>
    <p class="mt-2 text-sm text-gray-600">Configure global system settings</p>
  </div>

  <!-- Success Message -->
  {#if successMessage}
    <div class="mb-6 rounded-md bg-green-50 p-4" role="alert">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg
            class="h-5 w-5 text-green-400"
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
          <p class="text-sm font-medium text-green-800">{successMessage}</p>
        </div>
      </div>
    </div>
  {/if}

  <!-- Error Message -->
  {#if error}
    <div class="mb-6 rounded-md bg-red-50 p-4" role="alert">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg
            class="h-5 w-5 text-red-400"
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
          <p class="text-sm font-medium text-red-800">{error}</p>
        </div>
      </div>
    </div>
  {/if}

  {#if isLoading}
    <!-- Loading State -->
    <div class="flex items-center justify-center py-12">
      <svg
        class="h-8 w-8 animate-spin text-blue-600"
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
      <div class="overflow-hidden rounded-lg bg-white shadow">
        <div class="border-b border-gray-200 px-6 py-4">
          <h2 class="text-lg font-medium text-gray-900">Registration Settings</h2>
          <p class="mt-1 text-sm text-gray-500">
            Control how new users can register for the system
          </p>
        </div>

        <div class="space-y-6 px-6 py-5">
          <!-- Registration Mode -->
          <div>
            <label for="registration-mode" class="block text-sm font-medium text-gray-700">
              Registration Mode
            </label>
            <select
              id="registration-mode"
              value={registrationMode}
              onchange={handleRegistrationModeChange}
              class="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 sm:text-sm"
            >
              <option value="open">Open - Anyone can register</option>
              <option value="invitation">Invitation Only - Requires an invite code</option>
            </select>
            {#if settings.registration_mode?.description}
              <p class="mt-2 text-sm text-gray-500">{settings.registration_mode.description}</p>
            {/if}
            {#if settings.registration_mode?.updated_at}
              <p class="mt-1 text-xs text-gray-400">
                Last updated: {formatDate(settings.registration_mode.updated_at)}
              </p>
            {/if}
          </div>

          <!-- Allow Registration -->
          <div>
            <div class="flex items-center justify-between">
              <div class="flex-1">
                <label for="allow-registration" class="block text-sm font-medium text-gray-700">
                  Allow Registration
                </label>
                <p class="text-sm text-gray-500">Enable or disable new user registrations</p>
                {#if settings.allow_registration?.updated_at}
                  <p class="mt-1 text-xs text-gray-400">
                    Last updated: {formatDate(settings.allow_registration.updated_at)}
                  </p>
                {/if}
              </div>
              <button
                type="button"
                id="allow-registration"
                onclick={handleAllowRegistrationToggle}
                class="relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 {allowRegistration
                  ? 'bg-blue-600'
                  : 'bg-gray-200'}"
                role="switch"
                aria-checked={allowRegistration}
              >
                <span class="sr-only">Allow registration</span>
                <span
                  aria-hidden="true"
                  class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out {allowRegistration
                    ? 'translate-x-5'
                    : 'translate-x-0'}"
                ></span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Session Settings Card -->
      <div class="overflow-hidden rounded-lg bg-white shadow">
        <div class="border-b border-gray-200 px-6 py-4">
          <h2 class="text-lg font-medium text-gray-900">Session Settings</h2>
          <p class="mt-1 text-sm text-gray-500">Configure user session behavior</p>
        </div>

        <div class="space-y-6 px-6 py-5">
          <!-- Session Timeout -->
          <div>
            <label for="session-timeout" class="block text-sm font-medium text-gray-700">
              Session Timeout (minutes)
            </label>
            <input
              type="number"
              id="session-timeout"
              value={sessionTimeoutMinutes}
              oninput={handleSessionTimeoutChange}
              min="1"
              max="10080"
              class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 sm:text-sm"
            />
            <p class="mt-2 text-sm text-gray-500">
              How long a user session remains active without activity (1-10080 minutes)
            </p>
            {#if settings.session_timeout_minutes?.updated_at}
              <p class="mt-1 text-xs text-gray-400">
                Last updated: {formatDate(settings.session_timeout_minutes.updated_at)}
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
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Reset
        </button>
        <button
          type="submit"
          disabled={isSaving}
          class="inline-flex items-center rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
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
            Saving...
          {:else}
            Save Settings
          {/if}
        </button>
      </div>
    </form>
  {/if}
</div>
