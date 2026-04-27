<script lang="ts">
  /**
   * RestrictedToggles - Per-project capability toggle editor (Phase 8 / T402).
   *
   * Renders the eight `RestrictedConfig` keys (FR-014, FR-020-022) and
   * lets Owners / Admins persist changes via
   * `PATCH /web-api/v1/projects/{id}/restricted-config`.
   *
   * Visibility / permission gating
   * --------------------------------
   * - The toggles only apply to Restricted projects (FR-001 / FR-014).
   *   We render the editable form ONLY when
   *   `project.visibility === 'restricted'`. All other visibilities
   *   (including legacy `'private'`) get a notice instead, since
   *   posting to the PATCH endpoint would be rejected with 422
   *   `ERR_RESTRICTED_CONFIG_NOT_APPLICABLE` for non-restricted
   *   projects.
   * - When the caller is not allowed to edit
   *   (`canEdit === false`) we still render the toggles in a
   *   read-only state with a notice, so Members and Viewers can see
   *   the project's current posture without getting confused by a
   *   missing section.
   *
   * Save flow
   * ---------
   * Uses TanStack Query's `createMutation` so we get pending / error
   * states without re-implementing the lifecycle. On success we patch
   * the cached `Project` query (and `project-overview`) so other parts
   * of the page that read `restricted_config` rerender immediately.
   * On 422 with `ERR_RESTRICTED_CONFIG_NOT_APPLICABLE` we surface the
   * dedicated copy; on 403 we surface the no-permission copy. All
   * other backend errors fall through to the generic "save failed".
   *
   * Accessibility
   * -------------
   * - Each switch has a `<label for="..."> + <input type=checkbox>`
   *   pair plus a sibling description with `aria-describedby` so
   *   screen readers announce the description on focus.
   * - The H3 dropdown is a native `<select>` with a `<label for>` and
   *   a description. Native widgets ship with the right roles by
   *   default — we deliberately avoid recreating the wheel with
   *   `role="switch"`.
   *
   * Theme: Rosé Pine (Light=Dawn, Dark=Main). Colour tokens come from
   * the existing `tailwind.config` palette (`primary`, `surface-card`,
   * `danger`, etc.) so the component matches the rest of the project
   * detail page.
   */

  import { createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { projectsApi } from '$lib/api/projects';
  import { ApiError } from '$lib/api/client';
  import * as m from '$lib/paraglide/messages';
  import type {
    Project,
    RestrictedConfig,
    RestrictedConfigUpdateRequest,
    RestrictedH3Resolution,
  } from '$lib/types';

  interface Props {
    /**
     * Project whose restricted toggles should be edited. The component
     * needs `id`, `visibility`, and `restricted_config`. When the
     * project's `restricted_config` is missing (e.g. legacy responses)
     * we synthesise the default-OFF shape so the form still renders.
     */
    project: Project;
    /**
     * Whether the current user can edit the toggles. Owners + Admins
     * resolve to `true`; Members / Viewers / non-members → `false`.
     * The component still renders the toggles in read-only mode so
     * Members can see the project's current posture without being
     * surprised by a missing section.
     */
    canEdit: boolean;
  }

  let { project, canEdit }: Props = $props();

  const queryClient = useQueryClient();

  /**
   * Default-OFF restricted config — used when the project payload
   * does not carry a `restricted_config` (legacy responses or
   * mid-migration state). Mirrors the model column defaults.
   */
  const DEFAULT_CONFIG: RestrictedConfig = {
    allow_media_playback: false,
    allow_detection_view: false,
    mask_species_in_detection: false,
    allow_download: false,
    allow_export: false,
    allow_voting_and_comments: false,
    public_location_precision_h3_res: 2,
    allow_precise_location_to_viewer: false,
  };

  /**
   * Persisted shape from the server. Stored as `$state` (not `$derived`)
   * so the mutation success handler can replace it from the PATCH
   * response *immediately* — before the parent's query
   * invalidation+refetch completes — and flip `dirty` back to false
   * without waiting for the project re-fetch round-trip.
   *
   * We still seed it from the upstream `project.restricted_config` via
   * the `$effect` below so a fresh page load (or a parent-driven
   * refresh) picks up the latest server value as the new baseline.
   *
   * Initialised to DEFAULT_CONFIG so the module-level read does not
   * snapshot a non-reactive `project.*` reference (Svelte 5 lints
   * reads of reactive props at module scope as bug-shaped). The
   * `$effect` below seeds the real value on mount.
   */
  let serverConfig = $state<RestrictedConfig>({ ...DEFAULT_CONFIG });

  // Local draft state. Initialised from the server snapshot and synced
  // back when (a) the upstream `project.restricted_config` prop
  // changes (parent re-fetch path) or (b) the mutation success handler
  // replaces `serverConfig` with the PATCH response. The dirty flag
  // tracks divergence from `serverConfig`.
  let draft = $state<RestrictedConfig>({ ...DEFAULT_CONFIG });
  // Tracks the last `project.restricted_config` reference we seeded
  // from. Identity comparison is sufficient because Svelte's reactive
  // graph returns the same object reference until the prop updates.
  // We start at a sentinel symbol so the first effect run always
  // seeds, regardless of whether the prop is missing or set.
  const NEVER_SYNCED: unique symbol = Symbol('never-synced');
  let lastSyncedProp = $state<RestrictedConfig | null | undefined | typeof NEVER_SYNCED>(
    NEVER_SYNCED,
  );

  $effect(() => {
    // Re-seed from the prop only when the parent passes a new
    // `restricted_config` reference. The mutation success handler
    // assigns directly to `serverConfig` + `draft` and updates
    // `lastSyncedProp` to the parent's still-stale reference, so this
    // effect doesn't fight the in-place sync.
    const incoming = project.restricted_config;
    if (lastSyncedProp !== incoming) {
      const next = incoming ?? DEFAULT_CONFIG;
      serverConfig = next;
      draft = { ...next };
      lastSyncedProp = incoming;
    }
  });

  /**
   * Allowed H3 resolutions in descending privacy order. Lower number
   * = coarser hex = more protective.
   */
  const H3_OPTIONS: ReadonlyArray<RestrictedH3Resolution> = [2, 5, 7, 9, 15];

  function h3Label(value: RestrictedH3Resolution): string {
    switch (value) {
      case 2:
        return m.restricted_toggles_h3_res_2();
      case 5:
        return m.restricted_toggles_h3_res_5();
      case 7:
        return m.restricted_toggles_h3_res_7();
      case 9:
        return m.restricted_toggles_h3_res_9();
      case 15:
        return m.restricted_toggles_h3_res_15();
    }
  }

  /**
   * Dirty flag — true when the draft differs from the server snapshot.
   * We compare every key explicitly so a future spec change that adds
   * a new key fails to type-check until the comparison is updated.
   */
  const dirty = $derived(
    draft.allow_media_playback !== serverConfig.allow_media_playback ||
      draft.allow_detection_view !== serverConfig.allow_detection_view ||
      draft.mask_species_in_detection !== serverConfig.mask_species_in_detection ||
      draft.allow_download !== serverConfig.allow_download ||
      draft.allow_export !== serverConfig.allow_export ||
      draft.allow_voting_and_comments !== serverConfig.allow_voting_and_comments ||
      draft.public_location_precision_h3_res !==
        serverConfig.public_location_precision_h3_res ||
      draft.allow_precise_location_to_viewer !==
        serverConfig.allow_precise_location_to_viewer,
  );

  // Visual state for the inline result banner. We surface the success
  // / error inline (no toast library wired into the project) so the
  // outcome is announced near the form.
  let saveState = $state<
    | { kind: 'idle' }
    | { kind: 'success'; message: string }
    | { kind: 'error'; message: string }
  >({ kind: 'idle' });

  // The component is short-circuited for Public projects, but we still
  // declare the mutation at the top level so the hook count is stable.
  const updateMutation = createMutation<
    Project,
    Error,
    RestrictedConfigUpdateRequest
  >({
    mutationFn: (config) => projectsApi.updateRestrictedConfig(project.id, config),
    onSuccess: (updatedProject) => {
      // 1) Invalidate downstream queries so other parts of the app
      //    pick up the new toggle state. Project detail uses a
      //    non-TanStack load path (loadProject() in +page.svelte),
      //    but the project-overview query and any future TanStack
      //    callers need their cache bumped.
      queryClient.invalidateQueries({ queryKey: ['project', project.id] });
      queryClient.invalidateQueries({ queryKey: ['project-overview', project.id] });

      // 2) Sync `serverConfig` and `draft` to the freshly-returned
      //    PATCH response so the dirty flag flips back to false
      //    *immediately*, without waiting for the parent re-fetch.
      //    The PATCH endpoint always echoes the persisted shape so we
      //    treat the response as authoritative.
      const next = updatedProject.restricted_config ?? DEFAULT_CONFIG;
      serverConfig = next;
      draft = { ...next };
      // Keep the prop-sync effect quiet: we don't have a fresh prop
      // reference yet (the parent will refetch shortly), but we want
      // it to ignore the still-stale `project.restricted_config` and
      // accept whatever new reference arrives next.
      lastSyncedProp = project.restricted_config;
      saveState = { kind: 'success', message: m.restricted_toggles_save_success() };
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        if (err.status === 422 && err.code === 'ERR_RESTRICTED_CONFIG_NOT_APPLICABLE') {
          saveState = {
            kind: 'error',
            message: m.restricted_toggles_save_public_not_applicable(),
          };
          return;
        }
        if (err.status === 403) {
          saveState = {
            kind: 'error',
            message: m.restricted_toggles_save_no_permission(),
          };
          return;
        }
      }
      saveState = { kind: 'error', message: m.restricted_toggles_save_error() };
    },
  });

  function handleSave() {
    if (!dirty || $updateMutation.isPending) return;
    saveState = { kind: 'idle' };
    $updateMutation.mutate({ ...draft });
  }

  // The toggle form is only meaningful for Restricted projects (FR-014).
  // For all other visibilities — Public, legacy Private, or any future
  // visibility — we render a notice instead of the form so we can
  // never accidentally PATCH a project the backend would reject with
  // 422 ERR_RESTRICTED_CONFIG_NOT_APPLICABLE.
  const isRestricted = $derived(project.visibility === 'restricted');
  const isPublic = $derived(project.visibility === 'public');
  const inputsDisabled = $derived(!canEdit || $updateMutation.isPending);
</script>

<section
  data-testid="restricted-toggles-section"
  class="rounded-lg bg-surface-card p-6 shadow"
  aria-labelledby="restricted-toggles-heading"
>
  <header class="mb-4">
    <h2 id="restricted-toggles-heading" class="text-lg font-semibold text-stone-900">
      {m.restricted_toggles_section_title()}
    </h2>
    <p class="mt-1 text-sm text-stone-600">
      {m.restricted_toggles_section_description()}
    </p>
  </header>

  {#if isPublic}
    <!--
      FR-001 / FR-014: toggles only apply to Restricted projects. We
      render a stable notice (instead of hiding the section entirely)
      so the layout stays consistent and the visibility-flip is
      discoverable.
    -->
    <p
      data-testid="restricted-toggles-public-notice"
      class="rounded-md bg-info-light px-4 py-3 text-sm text-info"
      role="status"
    >
      {m.restricted_toggles_public_only_message()}
    </p>
  {:else if !isRestricted}
    <!--
      Legacy `'private'` visibility (or any non-public, non-restricted
      future value). The PATCH endpoint rejects these with 422
      ERR_RESTRICTED_CONFIG_NOT_APPLICABLE, so we render a non-editable
      notice instead of the form. This avoids dirty-state edits that
      can never be saved.
    -->
    <p
      data-testid="restricted-toggles-not-applicable-notice"
      class="rounded-md bg-stone-100 px-4 py-3 text-sm text-stone-600"
      role="status"
    >
      {m.restricted_toggles_not_applicable_message()}
    </p>
  {:else}
    {#if !canEdit}
      <p
        data-testid="restricted-toggles-no-permission-notice"
        class="mb-4 rounded-md bg-stone-100 px-4 py-3 text-sm text-stone-600"
        role="status"
      >
        {m.restricted_toggles_no_permission_message()}
      </p>
    {/if}

    <ul class="space-y-4" data-testid="restricted-toggles-list">
      <!--
        Each toggle is a checkbox visually styled as a switch. We use
        the native checkbox so the implicit `role` and keyboard
        handling work without ARIA workarounds.
      -->
      <li class="flex items-start gap-3">
        <input
          id="restricted-allow_media_playback"
          type="checkbox"
          data-testid="toggle-allow_media_playback"
          bind:checked={draft.allow_media_playback}
          disabled={inputsDisabled}
          aria-describedby="restricted-allow_media_playback-desc"
          class="mt-0.5 h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500 disabled:cursor-not-allowed disabled:opacity-60"
        />
        <div class="min-w-0 flex-1">
          <label
            for="restricted-allow_media_playback"
            class="block text-sm font-medium text-stone-700"
          >
            {m.restricted_toggles_allow_media_playback_label()}
          </label>
          <p
            id="restricted-allow_media_playback-desc"
            class="mt-0.5 text-xs text-stone-500"
          >
            {m.restricted_toggles_allow_media_playback_description()}
          </p>
        </div>
      </li>

      <li class="flex items-start gap-3">
        <input
          id="restricted-allow_detection_view"
          type="checkbox"
          data-testid="toggle-allow_detection_view"
          bind:checked={draft.allow_detection_view}
          disabled={inputsDisabled}
          aria-describedby="restricted-allow_detection_view-desc"
          class="mt-0.5 h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500 disabled:cursor-not-allowed disabled:opacity-60"
        />
        <div class="min-w-0 flex-1">
          <label
            for="restricted-allow_detection_view"
            class="block text-sm font-medium text-stone-700"
          >
            {m.restricted_toggles_allow_detection_view_label()}
          </label>
          <p
            id="restricted-allow_detection_view-desc"
            class="mt-0.5 text-xs text-stone-500"
          >
            {m.restricted_toggles_allow_detection_view_description()}
          </p>
        </div>
      </li>

      <li class="flex items-start gap-3">
        <input
          id="restricted-mask_species_in_detection"
          type="checkbox"
          data-testid="toggle-mask_species_in_detection"
          bind:checked={draft.mask_species_in_detection}
          disabled={inputsDisabled}
          aria-describedby="restricted-mask_species_in_detection-desc"
          class="mt-0.5 h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500 disabled:cursor-not-allowed disabled:opacity-60"
        />
        <div class="min-w-0 flex-1">
          <label
            for="restricted-mask_species_in_detection"
            class="block text-sm font-medium text-stone-700"
          >
            {m.restricted_toggles_mask_species_in_detection_label()}
          </label>
          <p
            id="restricted-mask_species_in_detection-desc"
            class="mt-0.5 text-xs text-stone-500"
          >
            {m.restricted_toggles_mask_species_in_detection_description()}
          </p>
        </div>
      </li>

      <li class="flex items-start gap-3">
        <input
          id="restricted-allow_download"
          type="checkbox"
          data-testid="toggle-allow_download"
          bind:checked={draft.allow_download}
          disabled={inputsDisabled}
          aria-describedby="restricted-allow_download-desc"
          class="mt-0.5 h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500 disabled:cursor-not-allowed disabled:opacity-60"
        />
        <div class="min-w-0 flex-1">
          <label
            for="restricted-allow_download"
            class="block text-sm font-medium text-stone-700"
          >
            {m.restricted_toggles_allow_download_label()}
          </label>
          <p id="restricted-allow_download-desc" class="mt-0.5 text-xs text-stone-500">
            {m.restricted_toggles_allow_download_description()}
          </p>
        </div>
      </li>

      <li class="flex items-start gap-3">
        <input
          id="restricted-allow_export"
          type="checkbox"
          data-testid="toggle-allow_export"
          bind:checked={draft.allow_export}
          disabled={inputsDisabled}
          aria-describedby="restricted-allow_export-desc"
          class="mt-0.5 h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500 disabled:cursor-not-allowed disabled:opacity-60"
        />
        <div class="min-w-0 flex-1">
          <label
            for="restricted-allow_export"
            class="block text-sm font-medium text-stone-700"
          >
            {m.restricted_toggles_allow_export_label()}
          </label>
          <p id="restricted-allow_export-desc" class="mt-0.5 text-xs text-stone-500">
            {m.restricted_toggles_allow_export_description()}
          </p>
        </div>
      </li>

      <li class="flex items-start gap-3">
        <input
          id="restricted-allow_voting_and_comments"
          type="checkbox"
          data-testid="toggle-allow_voting_and_comments"
          bind:checked={draft.allow_voting_and_comments}
          disabled={inputsDisabled}
          aria-describedby="restricted-allow_voting_and_comments-desc"
          class="mt-0.5 h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500 disabled:cursor-not-allowed disabled:opacity-60"
        />
        <div class="min-w-0 flex-1">
          <label
            for="restricted-allow_voting_and_comments"
            class="block text-sm font-medium text-stone-700"
          >
            {m.restricted_toggles_allow_voting_and_comments_label()}
          </label>
          <p
            id="restricted-allow_voting_and_comments-desc"
            class="mt-0.5 text-xs text-stone-500"
          >
            {m.restricted_toggles_allow_voting_and_comments_description()}
          </p>
        </div>
      </li>

      <li class="flex items-start gap-3">
        <div class="min-w-0 flex-1">
          <label
            for="restricted-h3_res"
            class="block text-sm font-medium text-stone-700"
          >
            {m.restricted_toggles_h3_res_label()}
          </label>
          <p id="restricted-h3_res-desc" class="mt-0.5 text-xs text-stone-500">
            {m.restricted_toggles_h3_res_description()}
          </p>
          <select
            id="restricted-h3_res"
            data-testid="toggle-public_location_precision_h3_res"
            bind:value={draft.public_location_precision_h3_res}
            disabled={inputsDisabled}
            aria-describedby="restricted-h3_res-desc"
            class="mt-2 block w-full max-w-xs rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:cursor-not-allowed disabled:bg-stone-100 disabled:opacity-60"
          >
            {#each H3_OPTIONS as option (option)}
              <option value={option}>{h3Label(option)}</option>
            {/each}
          </select>
        </div>
      </li>

      <li class="flex items-start gap-3">
        <input
          id="restricted-allow_precise_to_viewer"
          type="checkbox"
          data-testid="toggle-allow_precise_location_to_viewer"
          bind:checked={draft.allow_precise_location_to_viewer}
          disabled={inputsDisabled}
          aria-describedby="restricted-allow_precise_to_viewer-desc"
          class="mt-0.5 h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500 disabled:cursor-not-allowed disabled:opacity-60"
        />
        <div class="min-w-0 flex-1">
          <label
            for="restricted-allow_precise_to_viewer"
            class="block text-sm font-medium text-stone-700"
          >
            {m.restricted_toggles_allow_precise_to_viewer_label()}
          </label>
          <p
            id="restricted-allow_precise_to_viewer-desc"
            class="mt-0.5 text-xs text-stone-500"
          >
            {m.restricted_toggles_allow_precise_to_viewer_description()}
          </p>
        </div>
      </li>
    </ul>

    {#if saveState.kind === 'success'}
      <p
        data-testid="restricted-toggles-save-success"
        role="status"
        class="mt-4 rounded-md bg-success-light px-4 py-3 text-sm text-success"
      >
        {saveState.message}
      </p>
    {:else if saveState.kind === 'error'}
      <p
        data-testid="restricted-toggles-save-error"
        role="alert"
        class="mt-4 rounded-md bg-danger-light px-4 py-3 text-sm text-danger"
      >
        {saveState.message}
      </p>
    {/if}

    {#if canEdit}
      <div class="mt-6 flex justify-end">
        <button
          type="button"
          data-testid="restricted-toggles-save-button"
          onclick={handleSave}
          disabled={!dirty || $updateMutation.isPending}
          class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:hover:bg-primary-400"
        >
          {#if $updateMutation.isPending}
            <svg
              class="mr-2 h-4 w-4 animate-spin"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              aria-hidden="true"
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
            {m.restricted_toggles_saving_button()}
          {:else}
            {m.restricted_toggles_save_button()}
          {/if}
        </button>
      </div>
    {/if}
  {/if}
</section>
