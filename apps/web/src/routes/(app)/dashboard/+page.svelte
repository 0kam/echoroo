<script lang="ts">
  /**
   * Dashboard page - authenticated user home
   */

  import { authStore } from '$lib/stores/auth.svelte';
</script>

<svelte:head>
  <title>Dashboard - Echoroo</title>
</svelte:head>

<div class="flex-1 overflow-auto bg-gray-50">
  <!-- Main Content -->
  <main class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
    <!-- Welcome Section -->
    <div class="rounded-lg bg-white p-6 shadow">
      <h2 class="text-2xl font-semibold text-gray-900">
        Welcome{authStore.user?.display_name ? `, ${authStore.user.display_name}` : ''}!
      </h2>
      <p class="mt-2 text-gray-600">
        Welcome to Echoroo. Organize your bioacoustic monitoring work into projects, upload
        recordings, run ML-powered species detection, and review results.
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
      <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
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
            Manage your bioacoustic projects
          </p>
        </a>

        <!-- New Project Card -->
        <a
          href="/projects/new"
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
                d="M12 4v16m8-8H4"
              />
            </svg>
            <h4 class="ml-3 text-lg font-medium text-gray-900">New Project</h4>
          </div>
          <p class="mt-2 text-sm text-gray-600">
            Create a new monitoring project
          </p>
        </a>
      </div>
    </div>

    <!-- Workflow Overview -->
    <div class="mt-8 rounded-lg bg-blue-50 p-6">
      <h3 class="text-lg font-medium text-blue-900">How It Works</h3>
      <ol class="mt-4 space-y-4">
        <li class="flex items-start">
          <span class="mr-3 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
            1
          </span>
          <div>
            <p class="text-sm font-medium text-blue-900">Create a project</p>
            <p class="mt-0.5 text-sm text-blue-700">
              Set up a project to group your monitoring sites and recordings.
            </p>
          </div>
        </li>
        <li class="flex items-start">
          <span class="mr-3 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
            2
          </span>
          <div>
            <p class="text-sm font-medium text-blue-900">Add sites and upload recordings</p>
            <p class="mt-0.5 text-sm text-blue-700">
              Define monitoring sites and upload audio recordings from the field.
            </p>
          </div>
        </li>
        <li class="flex items-start">
          <span class="mr-3 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
            3
          </span>
          <div>
            <p class="text-sm font-medium text-blue-900">Run species detection</p>
            <p class="mt-0.5 text-sm text-blue-700">
              Use ML models (BirdNET, Perch) to automatically detect and classify species.
            </p>
          </div>
        </li>
        <li class="flex items-start">
          <span class="mr-3 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
            4
          </span>
          <div>
            <p class="text-sm font-medium text-blue-900">Review results</p>
            <p class="mt-0.5 text-sm text-blue-700">
              Validate detections, review spectrograms, and export findings as reports.
            </p>
          </div>
        </li>
      </ol>
    </div>
  </main>
</div>
