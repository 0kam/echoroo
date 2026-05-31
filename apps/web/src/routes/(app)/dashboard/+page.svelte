<script lang="ts">
  /**
   * Dashboard page - authenticated user home
   */

  import { authStore } from '$lib/stores/auth.svelte';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
</script>

<svelte:head>
  <title>{m.dashboard_page_title()}</title>
</svelte:head>

<div class="flex-1 overflow-auto bg-stone-50">
  <!-- Main Content -->
  <main class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
    <!-- Welcome Section -->
    <div class="rounded-lg bg-surface-card p-6 shadow">
      <h2 class="text-2xl font-semibold text-stone-900">
        {m.dashboard_welcome()}{authStore.user?.display_name ? `, ${authStore.user.display_name}` : ''}!
      </h2>
      <p class="mt-2 text-stone-600">
        {m.dashboard_description()}
      </p>

      {#if authStore.user}
        <div class="mt-6 border-t border-stone-200 pt-6">
          <dl class="grid grid-cols-1 gap-x-4 gap-y-6 sm:grid-cols-2">
            <div>
              <dt class="text-sm font-medium text-stone-500">{m.dashboard_email_label()}</dt>
              <dd class="mt-1 text-sm text-stone-900">{authStore.user.email}</dd>
            </div>
            <div>
              <dt class="text-sm font-medium text-stone-500">{m.dashboard_status_label()}</dt>
              <dd class="mt-1 text-sm text-stone-900">
                {#if authStore.user.is_superuser}
                  <span class="inline-flex rounded-full bg-primary-100 px-2 py-1 text-xs font-semibold leading-5 text-primary-800 dark:bg-primary-900/30 dark:text-primary-400">
                    {m.dashboard_status_admin()}
                  </span>
                {:else}
                  <span class="text-stone-500">—</span>
                {/if}
              </dd>
            </div>
            <div>
              <dt class="text-sm font-medium text-stone-500">{m.dashboard_member_since_label()}</dt>
              <dd class="mt-1 text-sm text-stone-900">
                {new Date(authStore.user.created_at).toLocaleDateString(getLocale())}
              </dd>
            </div>
          </dl>
        </div>
      {/if}
    </div>

    <!-- Quick Actions -->
    <div class="mt-8">
      <h3 class="text-lg font-medium text-stone-900">{m.dashboard_quick_actions()}</h3>
      <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <!-- Projects Card -->
        <a
          href={localizeHref('/projects')}
          class="block rounded-lg border border-card bg-surface-card p-6 hover:border-primary-500 hover:shadow-md"
        >
          <div class="flex items-center">
            <svg
              class="h-8 w-8 text-primary-600"
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
            <h4 class="ml-3 text-lg font-medium text-stone-900">{m.dashboard_projects_title()}</h4>
          </div>
          <p class="mt-2 text-sm text-stone-600">
            {m.dashboard_projects_description()}
          </p>
        </a>

        <!-- New Project Card -->
        <a
          href={localizeHref('/projects/new')}
          class="block rounded-lg border border-card bg-surface-card p-6 hover:border-primary-500 hover:shadow-md"
        >
          <div class="flex items-center">
            <svg
              class="h-8 w-8 text-primary-600"
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
            <h4 class="ml-3 text-lg font-medium text-stone-900">{m.dashboard_new_project_title()}</h4>
          </div>
          <p class="mt-2 text-sm text-stone-600">
            {m.dashboard_new_project_description()}
          </p>
        </a>
      </div>
    </div>

    <!-- Workflow Overview -->
    <div class="mt-8 rounded-lg bg-primary-50 p-6">
      <h3 class="text-lg font-medium text-primary-900">{m.dashboard_how_it_works()}</h3>
      <ol class="mt-4 space-y-4">
        <li class="flex items-start">
          <span class="mr-3 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-primary-600 text-xs font-bold text-white dark:bg-primary-500 dark:text-stone-50">
            1
          </span>
          <div>
            <p class="text-sm font-medium text-primary-900">{m.dashboard_step1_title()}</p>
            <p class="mt-0.5 text-sm text-primary-700">
              {m.dashboard_step1_body()}
            </p>
          </div>
        </li>
        <li class="flex items-start">
          <span class="mr-3 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-primary-600 text-xs font-bold text-white dark:bg-primary-500 dark:text-stone-50">
            2
          </span>
          <div>
            <p class="text-sm font-medium text-primary-900">{m.dashboard_step2_title()}</p>
            <p class="mt-0.5 text-sm text-primary-700">
              {m.dashboard_step2_body()}
            </p>
          </div>
        </li>
        <li class="flex items-start">
          <span class="mr-3 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-primary-600 text-xs font-bold text-white dark:bg-primary-500 dark:text-stone-50">
            3
          </span>
          <div>
            <p class="text-sm font-medium text-primary-900">{m.dashboard_step3_title()}</p>
            <p class="mt-0.5 text-sm text-primary-700">
              {m.dashboard_step3_body()}
            </p>
          </div>
        </li>
        <li class="flex items-start">
          <span class="mr-3 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-primary-600 text-xs font-bold text-white dark:bg-primary-500 dark:text-stone-50">
            4
          </span>
          <div>
            <p class="text-sm font-medium text-primary-900">{m.dashboard_step4_title()}</p>
            <p class="mt-0.5 text-sm text-primary-700">
              {m.dashboard_step4_body()}
            </p>
          </div>
        </li>
      </ol>
    </div>
  </main>
</div>
