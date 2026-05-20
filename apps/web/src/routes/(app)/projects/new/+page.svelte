<script lang="ts">
  /**
   * Create new project page
   */

  import { goto } from '$app/navigation';
  import { projectsApi } from '$lib/api/projects';
  import { ApiError } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { ProjectLicense } from '$lib/types';

  // License options (FR-085 — must match contracts/projects.yaml enum).
  // The label and hint are pulled from i18n at render time so locale switches
  // pick up the translated copy without re-mounting the component.
  const LICENSE_OPTIONS: ReadonlyArray<{ value: ProjectLicense }> = [
    { value: 'CC0' },
    { value: 'CC-BY' },
    { value: 'CC-BY-NC' },
    { value: 'CC-BY-SA' },
  ];

  // Form state
  let name = $state('');
  let description = $state('');
  let visibility = $state<'private' | 'public'>('private');
  // License is required (FR-085). Empty string is the "unselected" sentinel
  // that disables the submit button until the user picks one of the four
  // CC options. We narrow to ProjectLicense before sending to the API.
  let license = $state<'' | ProjectLicense>('');

  // Form validity guards (FR-085: license required, name required).
  // Submit button is disabled until BOTH name and license are filled in.
  const nameValid = $derived(name.trim().length > 0 && name.trim().length <= 200);
  const licenseSelected = $derived(license !== '');
  const visibilitySelected = $derived(visibility === 'private' || visibility === 'public');
  const formValid = $derived(nameValid && licenseSelected && visibilitySelected);

  /**
   * Resolve the localized "why is submit disabled?" copy based on which
   * required field is currently missing.
   *
   * Codex Round 2 flagged that surfacing a fixed "License is required" string
   * for every disabled state was misleading whenever license was already
   * picked but name/visibility were missing. The reason now mirrors the
   * actual gating field with this priority:
   *   1. license unselected → license-specific copy.
   *   2. visibility unselected → visibility-specific copy.
   *   3. name missing or too long → name-specific copy.
   *   4. multiple missing fields with license already chosen → generic copy.
   *
   * Returns null when the form is valid (so callers can suppress the
   * tooltip / aria-describedby reference entirely).
   */
  const submitDisabledReason = $derived.by(() => {
    if (formValid) return null;

    const missing = [!nameValid, !licenseSelected, !visibilitySelected].filter(Boolean).length;

    // When more than one required field is missing we cannot single out a
    // specific blocker — fall back to the generic "complete required fields"
    // copy so the announcement matches reality.
    if (missing > 1) {
      return m.project_new_submit_disabled_reason_general();
    }

    // Exactly one field is missing — surface its field-specific copy.
    if (!licenseSelected) {
      return m.project_new_submit_disabled_reason_license();
    }
    if (!visibilitySelected) {
      return m.project_new_submit_disabled_reason_visibility();
    }
    // Only name is missing at this point (license + visibility are both set).
    return m.project_new_submit_disabled_reason_name();
  });

  // Field-level error for the license field — surfaced inline under the
  // dropdown so screen readers pick it up via aria-describedby.
  let licenseFieldError = $state<string | null>(null);

  // UI state
  let isSubmitting = $state(false);
  let error = $state<string | null>(null);

  /**
   * Validate form
   */
  function validateForm(): boolean {
    licenseFieldError = null;

    if (!name.trim()) {
      error = m.project_new_name_required();
      return false;
    }

    if (name.length > 200) {
      error = m.project_new_name_too_long();
      return false;
    }

    // FR-085: license is required. Even though the submit button is disabled
    // when no license is picked, we still validate defensively so a bypass
    // (e.g. JS-disabled form post) cannot reach the API with an empty value.
    // Only the inline field error is set; the form-level alert is left null
    // so screen readers do not announce the same message twice (Major 2).
    if (license === '') {
      licenseFieldError = m.project_new_license_required();
      error = null;
      return false;
    }

    return true;
  }

  /**
   * Map a backend ApiError into either an inline field error or the
   * top-of-form alert.
   *
   * The backend (Phase 7+) returns FR-085's license-required failure as a
   * structured `{ "error": "ERR_LICENSE_REQUIRED", "message": "..." }`
   * envelope which `ApiClient` parses into `ApiError.code`. We branch on
   * the error code (NOT a regex over `detail`/`message`) so localized
   * messages and copy changes do not break the mapping.
   *
   * When a license-required error is mapped, the inline field error owns
   * the announcement (it carries `role="alert"`); the top-of-form banner
   * is suppressed to avoid screen readers reading the same text twice.
   * For all other server errors we surface the generic top-of-form alert.
   */
  function applyApiError(err: ApiError): void {
    if (err.code === 'ERR_LICENSE_REQUIRED') {
      licenseFieldError = m.project_new_license_required();
      // Suppress the form-level alert so screen readers only announce
      // the field-level error once (Major 2).
      error = null;
      return;
    }

    const detail = err.detail || err.message || '';
    error = detail || m.project_new_error();
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

    // After validation, license is guaranteed to be a ProjectLicense.
    // Narrow the type so the API call is type-safe.
    if (license === '') {
      // This branch is unreachable because validateForm() already returned
      // false above, but the explicit guard satisfies the TypeScript type
      // narrowing for projectsApi.create().
      return;
    }
    const selectedLicense: ProjectLicense = license;

    isSubmitting = true;

    try {
      const project = await projectsApi.create({
        name: name.trim(),
        description: description.trim() || undefined,
        visibility,
        license: selectedLicense,
      });

      // Redirect to project detail page
      await goto(localizeHref(`/projects/${project.id}`));
    } catch (err) {
      if (err instanceof ApiError) {
        applyApiError(err);
      } else {
        error = m.project_new_error();
      }
    } finally {
      isSubmitting = false;
    }
  }

  /**
   * Resolve the localized human label for a license enum value.
   */
  function licenseLabel(value: ProjectLicense): string {
    switch (value) {
      case 'CC0':
        return m.project_new_license_cc0();
      case 'CC-BY':
        return m.project_new_license_cc_by();
      case 'CC-BY-NC':
        return m.project_new_license_cc_by_nc();
      case 'CC-BY-SA':
        return m.project_new_license_cc_by_sa();
    }
  }

  /**
   * Resolve the localized hint copy for a license enum value.
   */
  function licenseHintText(value: '' | ProjectLicense): string {
    switch (value) {
      case 'CC0':
        return m.project_new_license_cc0_hint();
      case 'CC-BY':
        return m.project_new_license_cc_by_hint();
      case 'CC-BY-NC':
        return m.project_new_license_cc_by_nc_hint();
      case 'CC-BY-SA':
        return m.project_new_license_cc_by_sa_hint();
      case '':
        return m.project_new_license_help();
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
    <h1 class="text-3xl font-bold text-stone-900">{m.project_new_heading()}</h1>
    <p class="mt-2 text-sm text-stone-600">
      {m.project_new_description()}
    </p>
  </div>

  <!-- Error Message -->
  {#if error}
    <div
      class="mb-6 rounded-md bg-danger-light p-4"
      role="alert"
      data-testid="project-form-error"
    >
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

  <!-- Form -->
  <form onsubmit={handleSubmit} class="space-y-6">
    <div class="rounded-lg bg-surface-card shadow">
      <div class="space-y-6 p-6">
        <!-- Project Name -->
        <div>
          <label for="name" class="block text-sm font-medium text-stone-700">
            {m.project_new_name_label()} <span class="text-danger">*</span>
          </label>
          <input
            id="name"
            name="name"
            type="text"
            required
            bind:value={name}
            disabled={isSubmitting}
            class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
            placeholder={m.project_new_name_placeholder()}
          />
          <p class="mt-1 text-xs text-stone-500">{m.project_new_name_hint()}</p>
        </div>

        <!-- Description -->
        <div>
          <label for="description" class="block text-sm font-medium text-stone-700">
            {m.project_new_description_label()}
          </label>
          <textarea
            id="description"
            name="description"
            rows="4"
            bind:value={description}
            disabled={isSubmitting}
            class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
            placeholder={m.project_new_description_placeholder()}
          ></textarea>
          <p class="mt-1 text-xs text-stone-500">{m.project_new_description_hint()}</p>
        </div>

        <!-- Visibility -->
        <div>
          <span class="block text-sm font-medium text-stone-700" id="visibility-label">{m.project_new_visibility_label()}</span>
          <div class="mt-2 space-y-2" role="radiogroup" aria-labelledby="visibility-label">
            <label class="flex items-start">
              <input
                type="radio"
                name="visibility"
                value="private"
                bind:group={visibility}
                disabled={isSubmitting}
                class="mt-0.5 h-4 w-4 border-stone-300 text-primary-600 focus:ring-primary-500"
              />
              <div class="ml-3">
                <div class="flex items-center">
                  <svg class="mr-1.5 h-4 w-4 text-stone-500" fill="currentColor" viewBox="0 0 20 20">
                    <path
                      fill-rule="evenodd"
                      d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z"
                      clip-rule="evenodd"
                    />
                  </svg>
                  <span class="text-sm font-medium text-stone-700">{m.project_new_visibility_private_label()}</span>
                </div>
                <p class="text-xs text-stone-500">{m.project_new_visibility_private_hint()}</p>
              </div>
            </label>

            <label class="flex items-start">
              <input
                type="radio"
                name="visibility"
                value="public"
                bind:group={visibility}
                disabled={isSubmitting}
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
                  <span class="text-sm font-medium text-stone-700">{m.project_new_visibility_public_label()}</span>
                </div>
                <p class="text-xs text-stone-500">{m.project_new_visibility_public_hint()}</p>
              </div>
            </label>
          </div>
        </div>

        <!-- License (FR-085: required, no default selection) -->
        <div>
          <label for="license" class="block text-sm font-medium text-stone-700">
            {m.project_new_license_label()} <span class="text-danger">*</span>
          </label>
          <select
            id="license"
            name="license"
            required
            data-testid="license-select"
            aria-required="true"
            aria-invalid={licenseFieldError !== null}
            aria-describedby={licenseFieldError ? 'license-hint license-error' : 'license-hint'}
            bind:value={license}
            disabled={isSubmitting}
            onchange={() => {
              // Clear field-level error as soon as the user picks a valid
              // option so the inline message does not linger.
              if (license !== '') {
                licenseFieldError = null;
              }
            }}
            class="mt-1 block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
          >
            <option value="" disabled>{m.project_new_license_placeholder()}</option>
            {#each LICENSE_OPTIONS as option (option.value)}
              <option value={option.value}>{licenseLabel(option.value)}</option>
            {/each}
          </select>
          <p id="license-hint" class="mt-1 text-xs text-stone-500">
            {licenseHintText(license)}
          </p>
          {#if licenseFieldError}
            <p id="license-error" class="mt-1 text-xs text-danger" role="alert">
              {licenseFieldError}
            </p>
          {/if}
        </div>
      </div>

      <!-- Form Actions -->
      <div class="flex justify-end space-x-3 border-t border-stone-200 bg-stone-50 px-6 py-4">
        <button
          type="button"
          onclick={handleCancel}
          disabled={isSubmitting}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.project_new_cancel()}
        </button>
        <button
          type="submit"
          data-testid="project-create-submit"
          disabled={isSubmitting || !formValid}
          aria-describedby={submitDisabledReason && !isSubmitting ? 'submit-disabled-reason' : undefined}
          title={submitDisabledReason && !isSubmitting ? submitDisabledReason : undefined}
          class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
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
        <!--
          Visually-hidden tooltip text for screen readers. Always rendered
          (so `aria-describedby="submit-disabled-reason"` references a real
          node when set) but only conveyed via the button's aria reference
          while the form is invalid (Major 3 / spec.md acceptance §582).
          The copy mirrors the actual missing required field (Round 3 polish)
          so the announced reason is accurate, not a fixed string.
        -->
        <span id="submit-disabled-reason" class="sr-only">
          {submitDisabledReason ?? m.project_new_submit_disabled_reason_general()}
        </span>
      </div>
    </div>
  </form>
</div>
