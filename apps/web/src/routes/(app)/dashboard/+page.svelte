<script lang="ts">
  /**
   * Dashboard page - authenticated user home
   */

  import { authStore } from '$lib/stores/auth.svelte';
  import { goto } from '$app/navigation';

  /**
   * Handle logout
   */
  async function handleLogout() {
    await authStore.logout();
    await goto('/login');
  }
</script>

<svelte:head>
  <title>Dashboard - Echoroo</title>
</svelte:head>

<div class="min-h-screen bg-gray-50">
  <!-- Header -->
  <header class="bg-white shadow">
    <div class="mx-auto flex max-w-7xl items-center justify-between px-4 py-6 sm:px-6 lg:px-8">
      <h1 class="text-3xl font-bold text-gray-900">Dashboard</h1>
      <button
        type="button"
        onclick={handleLogout}
        class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
      >
        Logout
      </button>
    </div>
  </header>

  <!-- Main Content -->
  <main class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
    <!-- Welcome Section -->
    <div class="rounded-lg bg-white p-6 shadow">
      <h2 class="text-2xl font-semibold text-gray-900">
        Welcome{authStore.user?.display_name ? `, ${authStore.user.display_name}` : ''}!
      </h2>
      <p class="mt-2 text-gray-600">
        You're successfully logged in to Echoroo. This is your dashboard where you can manage your
        audio recordings and annotations.
      </p>

      {#if authStore.user}
        <div class="mt-6 border-t border-gray-200 pt-6">
          <dl class="grid grid-cols-1 gap-x-4 gap-y-6 sm:grid-cols-2">
            <div>
              <dt class="text-sm font-medium text-gray-500">Email</dt>
              <dd class="mt-1 text-sm text-gray-900">{authStore.user.email}</dd>
            </div>
            <div>
              <dt class="text-sm font-medium text-gray-500">Status</dt>
              <dd class="mt-1 text-sm text-gray-900">
                <span
                  class="inline-flex rounded-full px-2 py-1 text-xs font-semibold leading-5"
                  class:bg-green-100={authStore.user.is_verified}
                  class:text-green-800={authStore.user.is_verified}
                  class:bg-yellow-100={!authStore.user.is_verified}
                  class:text-yellow-800={!authStore.user.is_verified}
                >
                  {authStore.user.is_verified ? 'Verified' : 'Unverified'}
                </span>
                {#if authStore.user.is_superuser}
                  <span class="ml-2 inline-flex rounded-full bg-purple-100 px-2 py-1 text-xs font-semibold leading-5 text-purple-800">
                    Admin
                  </span>
                {/if}
              </dd>
            </div>
            <div>
              <dt class="text-sm font-medium text-gray-500">Member since</dt>
              <dd class="mt-1 text-sm text-gray-900">
                {new Date(authStore.user.created_at).toLocaleDateString()}
              </dd>
            </div>
          </dl>
        </div>
      {/if}
    </div>

    <!-- Quick Actions -->
    <div class="mt-8">
      <h3 class="text-lg font-medium text-gray-900">Quick Actions</h3>
      <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <!-- Recordings Card -->
        <a
          href="/recordings"
          class="block rounded-lg border border-gray-200 bg-white p-6 hover:border-blue-500 hover:shadow-md"
        >
          <div class="flex items-center">
            <svg
              class="h-8 w-8 text-blue-600"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
              />
            </svg>
            <h4 class="ml-3 text-lg font-medium text-gray-900">Recordings</h4>
          </div>
          <p class="mt-2 text-sm text-gray-600">
            View and manage your audio recordings
          </p>
        </a>

        <!-- Annotations Card -->
        <a
          href="/annotations"
          class="block rounded-lg border border-gray-200 bg-white p-6 hover:border-blue-500 hover:shadow-md"
        >
          <div class="flex items-center">
            <svg
              class="h-8 w-8 text-blue-600"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"
              />
            </svg>
            <h4 class="ml-3 text-lg font-medium text-gray-900">Annotations</h4>
          </div>
          <p class="mt-2 text-sm text-gray-600">
            Create and review annotations
          </p>
        </a>

        <!-- Projects Card -->
        <a
          href="/projects"
          class="block rounded-lg border border-gray-200 bg-white p-6 hover:border-blue-500 hover:shadow-md"
        >
          <div class="flex items-center">
            <svg
              class="h-8 w-8 text-blue-600"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
              />
            </svg>
            <h4 class="ml-3 text-lg font-medium text-gray-900">Projects</h4>
          </div>
          <p class="mt-2 text-sm text-gray-600">
            Organize your work into projects
          </p>
        </a>
      </div>
    </div>

    <!-- Getting Started -->
    <div class="mt-8 rounded-lg bg-blue-50 p-6">
      <h3 class="text-lg font-medium text-blue-900">Getting Started</h3>
      <ul class="mt-4 space-y-3 text-sm text-blue-800">
        <li class="flex items-start">
          <svg
            class="mr-2 h-5 w-5 flex-shrink-0 text-blue-600"
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
          Upload your first audio recording to get started
        </li>
        <li class="flex items-start">
          <svg
            class="mr-2 h-5 w-5 flex-shrink-0 text-blue-600"
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
          Create tags and annotations to organize your data
        </li>
        <li class="flex items-start">
          <svg
            class="mr-2 h-5 w-5 flex-shrink-0 text-blue-600"
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
          Use ML models to automatically detect and classify sounds
        </li>
      </ul>
    </div>
  </main>
</div>
