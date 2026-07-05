<script lang="ts">
  /**
   * ProjectSettingsForm — the validated edit form for a project's core
   * settings (name, description, target taxa, visibility).
   *
   * Extracted from the project settings page. Owns its own form-field state,
   * client-side validation, and the save/cancel flow. On a successful save it
   * notifies the parent via {@link Props.onSaved} so the parent can update the
   * shared project reference. Form fields re-initialize whenever the incoming
   * `project` reference changes (matching the original page, where a project
   * reload re-populated the fields).
   */
  import { goto } from '$app/navigation';
  import { ApiError } from '$lib/api/client';
  import { projectsApi } from '$lib/api/projects';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { Project } from '$lib/types';
  import TaxonSelector from './TaxonSelector.svelte';

  interface Props {
    projectId: string;
    /** Source project used to (re-)initialize the form fields. */
    project: Project;
    /**
     * Whether the caller may edit the project. The form only renders when
     * true, but the guard is preserved defensively before save.
     */
    hasAdminAccess: boolean;
    /** Called with the updated project after a successful save. */
    onSaved: (updated: Project) => void;
  }

  const { projectId, project, hasAdminAccess, onSaved }: Props = $props();

  const TARGET_TAXA_VALUES = [
    'Birds',
    'Anurans',
    'Insects',
    'Bats',
    'Land mammals',
    'Fishes',
    'Cetaceans',
  ];

  let name = $state('');
  let description = $state('');
  let selectedTaxa = $state<string[]>([]);
  const targetTaxa = $derived(selectedTaxa.join(', '));
  // Visibility radio supports public / restricted (Phase 8 / FR-014). The
  // selected value is round-tripped via projectData.visibility on save.
  let visibility = $state<'public' | 'restricted'>('restricted');

  let isSaving = $state(false);
  let error = $state<string | null>(null);
  let successMessage = $state<string | null>(null);

  // Re-initialize form fields from the source project. Reads only `project`
  // and writes the field state, so there is no reactive loop. This mirrors the
  // original page, where loading (or reloading) the project re-populated the
  // form fields.
  let lastProjectRef: Project | null = null;
  $effect(() => {
    if (project === lastProjectRef) return;
    lastProjectRef = project;
    name = project.name;
    description = project.description || '';
    const rawTaxa = project.target_taxa || '';
    selectedTaxa = rawTaxa
      ? rawTaxa
          .split(',')
          .map((t) => t.trim())
          .filter((t) => TARGET_TAXA_VALUES.includes(t))
      : [];
    visibility = project.visibility;
  });

  /**
   * Validate form
   */
  function validateForm(): boolean {
    if (!name.trim()) {
      error = m.project_settings_name_required();
      return false;
    }

    if (name.length > 200) {
      error = m.project_settings_name_too_long();
      return false;
    }

    return true;
  }

  /**
   * Save changes
   */
  async function handleSave(e: Event) {
    e.preventDefault();
    error = null;
    successMessage = null;

    if (!hasAdminAccess) {
      error = m.project_settings_error_permission();
      return;
    }

    if (!validateForm()) {
      return;
    }

    isSaving = true;

    try {
      const updated = await projectsApi.update(projectId, {
        name: name.trim(),
        description: description.trim() || undefined,
        target_taxa: targetTaxa || undefined,
        visibility,
      });

      successMessage = m.project_settings_save_success();
      onSaved(updated);

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.project_settings_error_save();
      }
    } finally {
      isSaving = false;
    }
  }

  /**
   * Cancel and go back
   */
  function handleCancel() {
    goto(localizeHref(`/projects/${projectId}`));
  }
</script>

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

<!-- Settings Form -->
<form onsubmit={handleSave} class="space-y-6">
  <div class="rounded-lg bg-surface-card shadow">
    <div class="space-y-6 p-6">
      <!-- Project Name -->
      <div>
        <label for="name" class="block text-sm font-medium text-stone-700">
          {m.project_settings_name_label()} <span class="text-danger">*</span>
        </label>
        <input
          id="name"
          name="name"
          type="text"
          required
          bind:value={name}
          disabled={isSaving}
          class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
          placeholder={m.project_settings_name_placeholder()}
        />
      </div>

      <!-- Description -->
      <div>
        <label for="description" class="block text-sm font-medium text-stone-700">
          {m.project_settings_description_label()}
        </label>
        <textarea
          id="description"
          name="description"
          rows="4"
          bind:value={description}
          disabled={isSaving}
          class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
          placeholder={m.project_settings_description_placeholder()}
        ></textarea>
      </div>

      <!-- Target Taxa -->
      <TaxonSelector bind:selectedTaxa disabled={isSaving} />

      <!-- Visibility -->
      <div>
        <span class="block text-sm font-medium text-stone-700" id="visibility-label">{m.project_settings_visibility_label()}</span>
        <!-- Visibility radio group: public or restricted. -->
        <div class="mt-2 space-y-2" role="radiogroup" aria-labelledby="visibility-label">
          <label class="flex items-start">
            <input
              type="radio"
              name="visibility"
              value="public"
              bind:group={visibility}
              disabled={isSaving}
              class="mt-0.5 h-4 w-4 border-stone-300 text-primary-600 focus:ring-primary-500"
            />
            <div class="ml-3">
              <div class="flex items-center">
                <svg class="mr-1.5 h-4 w-4 text-stone-500" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fill-rule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zM4.332 8.027a6.012 6.012 0 011.912-2.706C6.512 5.73 6.974 6 7.5 6A1.5 1.5 0 019 7.5V8a2 2 0 004 0 2 2 0 011.523-1.943A5.977 5.977 0 0116 10c0 .34-.028.675-.083 1H15a2 2 0 00-2 2v2.197A5.973 5.973 0 0110 16v-2a2 2 0 00-2-2 2 2 0 01-2-2 2 2 0 00-1.668-1.973z"
                    clip-rule="evenodd"
                  />
                </svg>
                <span class="text-sm font-medium text-stone-700">{m.project_settings_visibility_public_label()}</span>
              </div>
              <p class="text-xs text-stone-500">{m.project_settings_visibility_public_hint()}</p>
            </div>
          </label>

          <label class="flex items-start">
            <input
              type="radio"
              name="visibility"
              value="restricted"
              bind:group={visibility}
              disabled={isSaving}
              class="mt-0.5 h-4 w-4 border-stone-300 text-primary-600 focus:ring-primary-500"
            />
            <div class="ml-3">
              <div class="flex items-center">
                <svg class="mr-1.5 h-4 w-4 text-stone-500" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fill-rule="evenodd"
                    d="M18 8a6 6 0 01-7.743 5.743L10 14l-1 1-1 1H6v2H2v-4l4.257-4.257A6 6 0 1118 8zm-6-4a1 1 0 100 2 2 2 0 012 2 1 1 0 102 0 4 4 0 00-4-4z"
                    clip-rule="evenodd"
                  />
                </svg>
                <span class="text-sm font-medium text-stone-700">{m.project_settings_visibility_restricted_label()}</span>
              </div>
              <p class="text-xs text-stone-500">{m.project_settings_visibility_restricted_hint()}</p>
            </div>
          </label>
        </div>
      </div>
    </div>

    <!-- Form Actions -->
    <div class="flex justify-end space-x-3 border-t border-stone-200 bg-stone-50 px-6 py-4">
      <button
        type="button"
        onclick={handleCancel}
        disabled={isSaving}
        class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {m.project_settings_cancel()}
      </button>
      <button
        type="submit"
        disabled={isSaving}
        class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
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
          {m.project_settings_saving()}
        {:else}
          {m.project_settings_save()}
        {/if}
      </button>
    </div>
  </div>
</form>
