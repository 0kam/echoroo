<script lang="ts">
  /**
   * Profile page - manage user profile information
   */

  import { authStore } from '$lib/stores/auth.svelte';
  import {
    listTrustedDevices,
    revokeAllTrustedDevices,
    revokeTrustedDevice,
    type TrustedDevice,
  } from '$lib/api/trusted-devices';
  import { updateUser, type UpdateUserRequest } from '$lib/api/users';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import { onMount } from 'svelte';

  // Form state
  let displayName = $state(authStore.user?.display_name ?? '');
  let organization = $state(authStore.user?.organization ?? '');

  // UI state
  let isSubmitting = $state(false);
  let successMessage = $state('');
  let errorMessage = $state('');
  let trustedDevices = $state<TrustedDevice[]>([]);
  let isLoadingTrustedDevices = $state(false);
  let trustedDevicesError = $state('');
  let trustedDevicesSuccess = $state('');
  let revokingDeviceId = $state<string | null>(null);
  let isRevokingAllTrustedDevices = $state(false);

  // Track if form has changes
  let hasChanges = $derived(
    displayName !== (authStore.user?.display_name ?? '') ||
    organization !== (authStore.user?.organization ?? '')
  );

  onMount(() => {
    void loadTrustedDevices();
  });

  /**
   * Handle form submission
   */
  async function handleSubmit(event: Event) {
    event.preventDefault();

    if (isSubmitting || !hasChanges) return;

    isSubmitting = true;
    successMessage = '';
    errorMessage = '';

    try {
      const updateData: UpdateUserRequest = {};

      // Only include changed fields
      if (displayName !== (authStore.user?.display_name ?? '')) {
        updateData.display_name = displayName || null;
      }
      if (organization !== (authStore.user?.organization ?? '')) {
        updateData.organization = organization || null;
      }

      const updatedUser = await updateUser(updateData);
      authStore.setUser(updatedUser);

      successMessage = m.profile_save_success();

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = '';
      }, 3000);
    } catch (error: unknown) {
      if (error instanceof Error) {
        errorMessage = error.message;
      } else {
        errorMessage = m.profile_save_error();
      }
    } finally {
      isSubmitting = false;
    }
  }

  /**
   * Reset form to original values
   */
  function handleReset() {
    displayName = authStore.user?.display_name ?? '';
    organization = authStore.user?.organization ?? '';
    successMessage = '';
    errorMessage = '';
  }

  async function loadTrustedDevices() {
    isLoadingTrustedDevices = true;
    trustedDevicesError = '';

    try {
      const response = await listTrustedDevices();
      trustedDevices = response.devices;
    } catch {
      trustedDevicesError = 'Failed to load trusted devices. Please try again.';
    } finally {
      isLoadingTrustedDevices = false;
    }
  }

  async function handleRevokeTrustedDevice(deviceId: string) {
    if (revokingDeviceId || isRevokingAllTrustedDevices) return;

    revokingDeviceId = deviceId;
    trustedDevicesError = '';
    trustedDevicesSuccess = '';

    try {
      await revokeTrustedDevice(deviceId);
      trustedDevices = trustedDevices.filter((device) => device.id !== deviceId);
      trustedDevicesSuccess = 'Trusted device revoked.';
    } catch {
      trustedDevicesError = 'Failed to revoke trusted device. Please try again.';
    } finally {
      revokingDeviceId = null;
    }
  }

  async function handleRevokeAllTrustedDevices() {
    if (isRevokingAllTrustedDevices || revokingDeviceId || trustedDevices.length === 0) return;

    isRevokingAllTrustedDevices = true;
    trustedDevicesError = '';
    trustedDevicesSuccess = '';

    try {
      await revokeAllTrustedDevices();
      trustedDevices = [];
      trustedDevicesSuccess = 'All trusted devices revoked.';
    } catch {
      trustedDevicesError = 'Failed to revoke trusted devices. Please try again.';
    } finally {
      isRevokingAllTrustedDevices = false;
    }
  }

  function formatDeviceDate(value: string | null): string {
    if (!value) return '-';
    return new Date(value).toLocaleString(getLocale());
  }
</script>

<svelte:head>
  <title>{m.profile_page_title()}</title>
</svelte:head>

<div class="min-h-screen bg-stone-50">
  <!-- Header -->
  <header class="bg-surface-card shadow">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div class="flex items-center justify-between">
        <h1 class="text-3xl font-bold text-stone-900">{m.profile_heading()}</h1>
        <a
          href={localizeHref('/dashboard')}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
        >
          {m.profile_back_to_dashboard()}
        </a>
      </div>
    </div>
  </header>

  <!-- Main Content -->
  <main class="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
    <div class="overflow-hidden rounded-lg bg-surface-card shadow">
      <div class="px-4 py-5 sm:p-6">
        <h2 class="text-lg font-medium leading-6 text-stone-900">
          {m.profile_info_heading()}
        </h2>
        <p class="mt-1 text-sm text-stone-600">
          {m.profile_info_description()}
        </p>

        <!-- Success Message -->
        {#if successMessage}
          <div class="mt-4 rounded-md bg-success-light p-4">
            <div class="flex">
              <div class="flex-shrink-0">
                <svg class="h-5 w-5 text-success" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                </svg>
              </div>
              <div class="ml-3">
                <p class="text-sm font-medium text-success">{successMessage}</p>
              </div>
            </div>
          </div>
        {/if}

        <!-- Error Message -->
        {#if errorMessage}
          <div class="mt-4 rounded-md bg-danger-light p-4">
            <div class="flex">
              <div class="flex-shrink-0">
                <svg class="h-5 w-5 text-danger" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
                </svg>
              </div>
              <div class="ml-3">
                <p class="text-sm font-medium text-danger">{errorMessage}</p>
              </div>
            </div>
          </div>
        {/if}

        <form class="mt-6 space-y-6" onsubmit={handleSubmit}>
          <!-- Email (read-only) -->
          <div>
            <label for="email" class="block text-sm font-medium text-stone-700">
              {m.profile_email_label()}
            </label>
            <div class="mt-1">
              <input
                type="email"
                id="email"
                name="email"
                value={authStore.user?.email ?? ''}
                disabled
                class="block w-full rounded-md border-stone-300 bg-stone-100 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              />
            </div>
            <p class="mt-1 text-sm text-stone-500">
              {m.profile_email_cannot_change()}
            </p>
          </div>

          <!-- Display Name -->
          <div>
            <label for="display_name" class="block text-sm font-medium text-stone-700">
              {m.profile_display_name_label()}
            </label>
            <div class="mt-1">
              <input
                type="text"
                id="display_name"
                name="display_name"
                bind:value={displayName}
                maxlength="100"
                placeholder={m.profile_display_name_placeholder()}
                class="block w-full rounded-md border-stone-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              />
            </div>
            <p class="mt-1 text-sm text-stone-500">
              {m.profile_display_name_hint()}
            </p>
          </div>

          <!-- Organization -->
          <div>
            <label for="organization" class="block text-sm font-medium text-stone-700">
              {m.profile_organization_label()}
            </label>
            <div class="mt-1">
              <input
                type="text"
                id="organization"
                name="organization"
                bind:value={organization}
                maxlength="200"
                placeholder={m.profile_organization_placeholder()}
                class="block w-full rounded-md border-stone-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              />
            </div>
            <p class="mt-1 text-sm text-stone-500">
              {m.profile_organization_hint()}
            </p>
          </div>

          <!-- Account Information -->
          <div class="border-t border-stone-200 pt-6">
            <h3 class="text-sm font-medium text-stone-700">{m.profile_account_info_heading()}</h3>
            <dl class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <dt class="text-sm font-medium text-stone-500">{m.profile_status_label()}</dt>
                <dd class="mt-1 text-sm text-stone-900">
                  {#if authStore.user?.is_superuser}
                    <span class="inline-flex rounded-full bg-primary-100 px-2 py-1 text-xs font-semibold leading-5 text-primary-800 dark:bg-primary-900/30 dark:text-primary-400">
                      {m.profile_status_admin()}
                    </span>
                  {:else}
                    <span class="text-stone-500">—</span>
                  {/if}
                </dd>
              </div>
              <div>
                <dt class="text-sm font-medium text-stone-500">{m.profile_member_since_label()}</dt>
                <dd class="mt-1 text-sm text-stone-900">
                  {authStore.user?.created_at
                    ? new Date(authStore.user.created_at).toLocaleDateString(getLocale())
                    : '-'}
                </dd>
              </div>
              <div>
                <dt class="text-sm font-medium text-stone-500">{m.profile_last_login_label()}</dt>
                <dd class="mt-1 text-sm text-stone-900">
                  {authStore.user?.last_login_at
                    ? new Date(authStore.user.last_login_at).toLocaleString(getLocale())
                    : m.profile_last_login_never()}
                </dd>
              </div>
            </dl>
          </div>

          <!-- Form Actions -->
          <div class="flex justify-end space-x-3 border-t border-stone-200 pt-6">
            <button
              type="button"
              onclick={handleReset}
              disabled={!hasChanges || isSubmitting}
              class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {m.profile_reset_button()}
            </button>
            <button
              type="submit"
              disabled={!hasChanges || isSubmitting}
              class="inline-flex items-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
            >
              {#if isSubmitting}
                <svg class="-ml-1 mr-2 h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                {m.profile_saving()}
              {:else}
                {m.profile_save_button()}
              {/if}
            </button>
          </div>
        </form>

        <!-- Trusted Devices -->
        <section class="mt-8 border-t border-stone-200 pt-6" aria-labelledby="trusted-devices-heading">
          <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 id="trusted-devices-heading" class="text-lg font-medium leading-6 text-stone-900">
                Trusted devices
              </h2>
              <p class="mt-1 text-sm text-stone-600">
                Devices you trusted during two-factor sign-in can skip 2FA until they expire.
              </p>
            </div>
            <button
              type="button"
              onclick={handleRevokeAllTrustedDevices}
              disabled={isLoadingTrustedDevices || isRevokingAllTrustedDevices || trustedDevices.length === 0}
              class="inline-flex items-center justify-center rounded-md border border-danger bg-surface-card px-3 py-2 text-sm font-medium text-danger hover:bg-danger-light focus:outline-none focus:ring-2 focus:ring-danger focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isRevokingAllTrustedDevices ? 'Revoking...' : 'Revoke all'}
            </button>
          </div>

          {#if trustedDevicesSuccess}
            <p class="mt-4 text-sm font-medium text-success" role="status">{trustedDevicesSuccess}</p>
          {/if}
          {#if trustedDevicesError}
            <p class="mt-4 text-sm font-medium text-danger" role="alert">{trustedDevicesError}</p>
          {/if}

          <div class="mt-4 overflow-hidden rounded-md border border-stone-200">
            {#if isLoadingTrustedDevices}
              <p class="bg-stone-50 px-4 py-4 text-sm text-stone-600">Loading trusted devices...</p>
            {:else if trustedDevices.length === 0}
              <p class="bg-stone-50 px-4 py-4 text-sm text-stone-600">No trusted devices.</p>
            {:else}
              <ul class="divide-y divide-stone-200">
                {#each trustedDevices as device}
                  <li class="bg-surface-card px-4 py-4">
                    <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div class="min-w-0">
                        <div class="flex flex-wrap items-center gap-2">
                          <p class="break-words text-sm font-medium text-stone-900">
                            {device.label || 'Trusted device'}
                          </p>
                          {#if device.current_device}
                            <span class="inline-flex rounded-full bg-primary-100 px-2 py-1 text-xs font-semibold leading-5 text-primary-800 dark:bg-primary-900/30 dark:text-primary-400">
                              Current device
                            </span>
                          {/if}
                        </div>
                        {#if device.last_seen_hint}
                          <p class="mt-1 text-sm text-stone-600">{device.last_seen_hint}</p>
                        {/if}
                        <dl class="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-xs text-stone-500 sm:grid-cols-2">
                          <div>
                            <dt class="font-medium">Created</dt>
                            <dd>{formatDeviceDate(device.created_at)}</dd>
                          </div>
                          <div>
                            <dt class="font-medium">Last used</dt>
                            <dd>{formatDeviceDate(device.last_used_at)}</dd>
                          </div>
                          <div>
                            <dt class="font-medium">Expires</dt>
                            <dd>{formatDeviceDate(device.expires_at)}</dd>
                          </div>
                        </dl>
                      </div>
                      <button
                        type="button"
                        onclick={() => handleRevokeTrustedDevice(device.id)}
                        disabled={revokingDeviceId === device.id || isRevokingAllTrustedDevices}
                        class="inline-flex items-center justify-center rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {revokingDeviceId === device.id ? 'Revoking...' : 'Revoke'}
                      </button>
                    </div>
                  </li>
                {/each}
              </ul>
            {/if}
          </div>
        </section>

        <!-- Additional Settings -->
        <div class="mt-8 space-y-6 border-t border-stone-200 pt-6">
          <!-- Security Link -->
          <div>
            <a
              href={localizeHref('/settings')}
              class="inline-flex items-center text-sm font-medium text-primary-600 hover:text-primary-500"
            >
              <svg class="mr-2 h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
              {m.profile_security_link()}
            </a>
            <p class="mt-1 text-sm text-stone-500">
              {m.profile_security_description()}
            </p>
          </div>

          <!-- API Tokens Link -->
          <div>
            <a
              href={localizeHref('/profile/api-tokens')}
              class="inline-flex items-center text-sm font-medium text-primary-600 hover:text-primary-500"
            >
              <svg class="mr-2 h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
              </svg>
              {m.profile_api_tokens_link()}
            </a>
            <p class="mt-1 text-sm text-stone-500">
              {m.profile_api_tokens_description()}
            </p>
          </div>
        </div>
      </div>
    </div>
  </main>
</div>
