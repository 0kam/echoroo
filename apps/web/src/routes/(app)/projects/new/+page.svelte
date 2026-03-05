<script lang="ts">
  /**
   * Create new project page
   */

  import { goto } from '$app/navigation';
  import { projectsApi } from '$lib/api/projects';
  import { ApiError } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  // Predefined taxa options
  const TARGET_TAXA_OPTIONS = [
    { value: 'Birds', label: 'Birds' },
    { value: 'Anurans', label: 'Anurans' },
    { value: 'Insects', label: 'Insects' },
    { value: 'Bats', label: 'Bats' },
    { value: 'Land mammals', label: 'Land mammals' },
    { value: 'Fishes', label: 'Fishes' },
    { value: 'Cetaceans', label: 'Cetaceans' },
  ];

  // Form state
  let name = $state('');
  let description = $state('');
  let selectedTaxa = $state<string[]>([]);
  let visibility = $state<'private' | 'public'>('private');

  // Derived comma-separated string for API
  const targetTaxa = $derived(selectedTaxa.join(', '));

  /**
   * Toggle a taxon selection
   */
  function toggleTaxon(value: string) {
    if (selectedTaxa.includes(value)) {
      selectedTaxa = selectedTaxa.filter((t) => t !== value);
    } else {
      selectedTaxa = [...selectedTaxa, value];
    }
  }

  // UI state
  let isSubmitting = $state(false);
  let error = $state<string | null>(null);

  /**
   * Validate form
   */
  function validateForm(): boolean {
    if (!name.trim()) {
      error = m.project_new_name_required();
      return false;
    }

    if (name.length > 200) {
      error = m.project_new_name_too_long();
      return false;
    }

    return true;
  }

  /**
   * Handle form submission
   */
  async function handleSubmit(e: Event) {
    e.preventDefault();
    error = null;

    if (!validateForm()) {
      return;
    }

    isSubmitting = true;

    try {
      const project = await projectsApi.create({
        name: name.trim(),
        description: description.trim() || undefined,
        target_taxa: targetTaxa || undefined,
        visibility,
      });

      // Redirect to project detail page
      await goto(localizeHref(`/projects/${project.id}`));
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.project_new_error();
      }
    } finally {
      isSubmitting = false;
    }
  }

  /**
   * Cancel and go back
   */
  function handleCancel() {
    goto(localizeHref('/projects'));
  }
</script>

<svelte:head>
  <title>{m.project_new_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
  <!-- Header -->
  <div class="mb-8">
    <h1 class="text-3xl font-bold text-gray-900">{m.project_new_heading()}</h1>
    <p class="mt-2 text-sm text-gray-600">
      {m.project_new_description()}
    </p>
  </div>

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

  <!-- Form -->
  <form onsubmit={handleSubmit} class="space-y-6">
    <div class="rounded-lg bg-white shadow">
      <div class="space-y-6 p-6">
        <!-- Project Name -->
        <div>
          <label for="name" class="block text-sm font-medium text-gray-700">
            {m.project_new_name_label()} <span class="text-red-500">*</span>
          </label>
          <input
            id="name"
            name="name"
            type="text"
            required
            bind:value={name}
            disabled={isSubmitting}
            class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed sm:text-sm"
            placeholder={m.project_new_name_placeholder()}
          />
          <p class="mt-1 text-xs text-gray-500">{m.project_new_name_hint()}</p>
        </div>

        <!-- Description -->
        <div>
          <label for="description" class="block text-sm font-medium text-gray-700">
            {m.project_new_description_label()}
          </label>
          <textarea
            id="description"
            name="description"
            rows="4"
            bind:value={description}
            disabled={isSubmitting}
            class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed sm:text-sm"
            placeholder={m.project_new_description_placeholder()}
          ></textarea>
          <p class="mt-1 text-xs text-gray-500">{m.project_new_description_hint()}</p>
        </div>

        <!-- Target Taxa -->
        <div>
          <span class="block text-sm font-medium text-gray-700" id="target-taxa-label">
            {m.project_new_target_taxa_label()}
          </span>
          <div
            class="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3"
            role="group"
            aria-labelledby="target-taxa-label"
          >
            {#each TARGET_TAXA_OPTIONS as option (option.value)}
              <label
                class="flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors
                  {selectedTaxa.includes(option.value)
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
                  : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}
                  {isSubmitting ? 'cursor-not-allowed opacity-50' : ''}"
              >
                <input
                  type="checkbox"
                  value={option.value}
                  checked={selectedTaxa.includes(option.value)}
                  disabled={isSubmitting}
                  onchange={() => toggleTaxon(option.value)}
                  class="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                {option.label}
              </label>
            {/each}
          </div>
          <p class="mt-1 text-xs text-gray-500">
            {m.project_new_target_taxa_hint()}
          </p>
        </div>

        <!-- Visibility -->
        <div>
          <span class="block text-sm font-medium text-gray-700" id="visibility-label">{m.project_new_visibility_label()}</span>
          <div class="mt-2 space-y-2" role="radiogroup" aria-labelledby="visibility-label">
            <label class="flex items-start">
              <input
                type="radio"
                name="visibility"
                value="private"
                bind:group={visibility}
                disabled={isSubmitting}
                class="mt-0.5 h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <div class="ml-3">
                <div class="flex items-center">
                  <svg class="mr-1.5 h-4 w-4 text-gray-500" fill="currentColor" viewBox="0 0 20 20">
                    <path
                      fill-rule="evenodd"
                      d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z"
                      clip-rule="evenodd"
                    />
                  </svg>
                  <span class="text-sm font-medium text-gray-700">{m.project_new_visibility_private_label()}</span>
                </div>
                <p class="text-xs text-gray-500">{m.project_new_visibility_private_hint()}</p>
              </div>
            </label>

            <label class="flex items-start">
              <input
                type="radio"
                name="visibility"
                value="public"
                bind:group={visibility}
                disabled={isSubmitting}
                class="mt-0.5 h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <div class="ml-3">
                <div class="flex items-center">
                  <svg class="mr-1.5 h-4 w-4 text-gray-500" fill="currentColor" viewBox="0 0 20 20">
                    <path
                      fill-rule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zM4.332 8.027a6.012 6.012 0 011.912-2.706C6.512 5.73 6.974 6 7.5 6A1.5 1.5 0 019 7.5V8a2 2 0 004 0 2 2 0 011.523-1.943A5.977 5.977 0 0116 10c0 .34-.028.675-.083 1H15a2 2 0 00-2 2v2.197A5.973 5.973 0 0110 16v-2a2 2 0 00-2-2 2 2 0 01-2-2 2 2 0 00-1.668-1.973z"
                      clip-rule="evenodd"
                    />
                  </svg>
                  <span class="text-sm font-medium text-gray-700">{m.project_new_visibility_public_label()}</span>
                </div>
                <p class="text-xs text-gray-500">{m.project_new_visibility_public_hint()}</p>
              </div>
            </label>
          </div>
        </div>
      </div>

      <!-- Form Actions -->
      <div class="flex justify-end space-x-3 border-t border-gray-200 bg-gray-50 px-6 py-4">
        <button
          type="button"
          onclick={handleCancel}
          disabled={isSubmitting}
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.project_new_cancel()}
        </button>
        <button
          type="submit"
          disabled={isSubmitting}
          class="inline-flex items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {#if isSubmitting}
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
            {m.project_new_submitting()}
          {:else}
            {m.project_new_submit()}
          {/if}
        </button>
      </div>
    </div>
  </form>
</div>
