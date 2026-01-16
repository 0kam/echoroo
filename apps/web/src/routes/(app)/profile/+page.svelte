<script lang="ts">
  /**
   * Profile page - manage user profile information
   */

  import { authStore } from '$lib/stores/auth.svelte';
  import { updateUser, type UpdateUserRequest } from '$lib/api/users';

  // Form state
  let displayName = $state(authStore.user?.display_name ?? '');
  let organization = $state(authStore.user?.organization ?? '');

  // UI state
  let isSubmitting = $state(false);
  let successMessage = $state('');
  let errorMessage = $state('');

  // Track if form has changes
  let hasChanges = $derived(
    displayName !== (authStore.user?.display_name ?? '') ||
    organization !== (authStore.user?.organization ?? '')
  );

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

      successMessage = 'Profile updated successfully';

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = '';
      }, 3000);
    } catch (error: unknown) {
      if (error instanceof Error) {
        errorMessage = error.message;
      } else {
        errorMessage = 'Failed to update profile';
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
</script>

<svelte:head>
  <title>Profile - Echoroo</title>
</svelte:head>

<div class="min-h-screen bg-gray-50">
  <!-- Header -->
  <header class="bg-white shadow">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div class="flex items-center justify-between">
        <h1 class="text-3xl font-bold text-gray-900">Profile</h1>
        <a
          href="/dashboard"
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          Back to Dashboard
        </a>
      </div>
    </div>
  </header>

  <!-- Main Content -->
  <main class="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
    <div class="overflow-hidden rounded-lg bg-white shadow">
      <div class="px-4 py-5 sm:p-6">
        <h2 class="text-lg font-medium leading-6 text-gray-900">
          Profile Information
        </h2>
        <p class="mt-1 text-sm text-gray-600">
          Update your display name and organization information.
        </p>

        <!-- Success Message -->
        {#if successMessage}
          <div class="mt-4 rounded-md bg-green-50 p-4">
            <div class="flex">
              <div class="flex-shrink-0">
                <svg class="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                </svg>
              </div>
              <div class="ml-3">
                <p class="text-sm font-medium text-green-800">{successMessage}</p>
              </div>
            </div>
          </div>
        {/if}

        <!-- Error Message -->
        {#if errorMessage}
          <div class="mt-4 rounded-md bg-red-50 p-4">
            <div class="flex">
              <div class="flex-shrink-0">
                <svg class="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
                </svg>
              </div>
              <div class="ml-3">
                <p class="text-sm font-medium text-red-800">{errorMessage}</p>
              </div>
            </div>
          </div>
        {/if}

        <form class="mt-6 space-y-6" onsubmit={handleSubmit}>
          <!-- Email (read-only) -->
          <div>
            <label for="email" class="block text-sm font-medium text-gray-700">
              Email address
            </label>
            <div class="mt-1">
              <input
                type="email"
                id="email"
                name="email"
                value={authStore.user?.email ?? ''}
                disabled
                class="block w-full rounded-md border-gray-300 bg-gray-100 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              />
            </div>
            <p class="mt-1 text-sm text-gray-500">
              Your email address cannot be changed.
            </p>
          </div>

          <!-- Display Name -->
          <div>
            <label for="display_name" class="block text-sm font-medium text-gray-700">
              Display name
            </label>
            <div class="mt-1">
              <input
                type="text"
                id="display_name"
                name="display_name"
                bind:value={displayName}
                maxlength="100"
                placeholder="Enter your display name"
                class="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              />
            </div>
            <p class="mt-1 text-sm text-gray-500">
              This name will be shown to other users. Maximum 100 characters.
            </p>
          </div>

          <!-- Organization -->
          <div>
            <label for="organization" class="block text-sm font-medium text-gray-700">
              Organization
            </label>
            <div class="mt-1">
              <input
                type="text"
                id="organization"
                name="organization"
                bind:value={organization}
                maxlength="200"
                placeholder="Enter your organization or affiliation"
                class="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              />
            </div>
            <p class="mt-1 text-sm text-gray-500">
              Your organization or affiliation. Maximum 200 characters.
            </p>
          </div>

          <!-- Account Information -->
          <div class="border-t border-gray-200 pt-6">
            <h3 class="text-sm font-medium text-gray-700">Account Information</h3>
            <dl class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <dt class="text-sm font-medium text-gray-500">Status</dt>
                <dd class="mt-1 text-sm text-gray-900">
                  <span
                    class="inline-flex rounded-full px-2 py-1 text-xs font-semibold leading-5"
                    class:bg-green-100={authStore.user?.is_verified}
                    class:text-green-800={authStore.user?.is_verified}
                    class:bg-yellow-100={!authStore.user?.is_verified}
                    class:text-yellow-800={!authStore.user?.is_verified}
                  >
                    {authStore.user?.is_verified ? 'Verified' : 'Unverified'}
                  </span>
                  {#if authStore.user?.is_superuser}
                    <span class="ml-2 inline-flex rounded-full bg-purple-100 px-2 py-1 text-xs font-semibold leading-5 text-purple-800">
                      Admin
                    </span>
                  {/if}
                </dd>
              </div>
              <div>
                <dt class="text-sm font-medium text-gray-500">Member since</dt>
                <dd class="mt-1 text-sm text-gray-900">
                  {authStore.user?.created_at
                    ? new Date(authStore.user.created_at).toLocaleDateString()
                    : '-'}
                </dd>
              </div>
              <div>
                <dt class="text-sm font-medium text-gray-500">Last login</dt>
                <dd class="mt-1 text-sm text-gray-900">
                  {authStore.user?.last_login_at
                    ? new Date(authStore.user.last_login_at).toLocaleString()
                    : 'Never'}
                </dd>
              </div>
            </dl>
          </div>

          <!-- Form Actions -->
          <div class="flex justify-end space-x-3 border-t border-gray-200 pt-6">
            <button
              type="button"
              onclick={handleReset}
              disabled={!hasChanges || isSubmitting}
              class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Reset
            </button>
            <button
              type="submit"
              disabled={!hasChanges || isSubmitting}
              class="inline-flex items-center rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {#if isSubmitting}
                <svg class="-ml-1 mr-2 h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Saving...
              {:else}
                Save Changes
              {/if}
            </button>
          </div>
        </form>

        <!-- Additional Settings -->
        <div class="mt-8 space-y-6 border-t border-gray-200 pt-6">
          <!-- Security Link -->
          <div>
            <a
              href="/settings"
              class="inline-flex items-center text-sm font-medium text-blue-600 hover:text-blue-500"
            >
              <svg class="mr-2 h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
              Security Settings
            </a>
            <p class="mt-1 text-sm text-gray-500">
              Manage your password and security settings.
            </p>
          </div>

          <!-- API Tokens Link -->
          <div>
            <a
              href="/profile/api-tokens"
              class="inline-flex items-center text-sm font-medium text-blue-600 hover:text-blue-500"
            >
              <svg class="mr-2 h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
              </svg>
              API Tokens
            </a>
            <p class="mt-1 text-sm text-gray-500">
              Manage API tokens for programmatic access.
            </p>
          </div>
        </div>
      </div>
    </div>
  </main>
</div>
