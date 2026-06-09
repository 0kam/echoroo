<script lang="ts">
  /**
   * CreateModelFromSessionDialog - Two-step dialog to create a custom model
   * from an existing search session.
   *
   * Step 1: POST /custom-models with search_session_id
   * Step 2: POST /custom-models/{id}/seed-samples with search_session_id
   *
   * If Step 2 fails the user is still navigated to the new model so they
   * can retry sampling manually.
   */

  import * as m from '$lib/paraglide/messages';
  import { createTag } from '$lib/api/tags';
  import { createCustomModel, generateSeedSamples } from '$lib/api/custom-models';
  import type { SearchSession } from '$lib/types/search';
  import type { TagCreate } from '$lib/types/tag';
  import { formatSpeciesName } from '$lib/utils/speciesFormatters';

  interface SpeciesConfig {
    tag_id: string | null;
    scientific_name: string;
    common_name: string | null;
  }

  interface Props {
    projectId: string;
    session: SearchSession;
    /** The single species to train for. Parent must pick one if multi-species. */
    speciesConfig: SpeciesConfig;
    open: boolean;
    onClose: () => void;
    onSuccess: (modelId: string, opts?: { samplingFailed?: boolean; error?: string }) => void;
  }

  let { projectId, session, speciesConfig, open, onClose, onSuccess }: Props = $props();

  // ============================================
  // Form state
  // ============================================

  const suggestedName = $derived(
    `${speciesConfig.scientific_name} classifier`
  );

  // modelName is initialized empty and populated by the $effect below
  // when the dialog opens (or reopens with a new species), which keeps
  // the user's edits during the open session while avoiding a
  // state_referenced_locally warning.
  let modelName = $state('');
  let easyPositiveK = $state(5);
  let boundaryM = $state(10);
  let othersP = $state(20);
  let showAdvanced = $state(false);
  let isSubmitting = $state(false);
  let error = $state<string | null>(null);

  // Reset form when dialog opens
  $effect(() => {
    if (open) {
      modelName = suggestedName;
      easyPositiveK = 5;
      boundaryM = 10;
      othersP = 20;
      showAdvanced = false;
      error = null;
    }
  });

  // ============================================
  // Submit handler
  // ============================================

  async function handleSubmit() {
    error = null;

    if (!modelName.trim()) {
      error = m.models_train_model_name_required();
      return;
    }

    isSubmitting = true;
    try {
      // Resolve or create the target tag
      let tagId = speciesConfig.tag_id;

      if (!tagId) {
        const tagData: TagCreate = {
          name: speciesConfig.scientific_name,
          category: 'species',
          scientific_name: speciesConfig.scientific_name,
          common_name: speciesConfig.common_name ?? undefined,
        };
        const newTag = await createTag(projectId, tagData);
        tagId = newTag.id;
      }

      // Step 1: Create the model
      const model = await createCustomModel(projectId, {
        name: modelName.trim(),
        target_tag_id: tagId,
        search_session_id: session.id,
      });

      // Step 2: Kick off seed sampling (best-effort)
      try {
        await generateSeedSamples(projectId, model.id, {
          search_session_id: session.id,
          config: {
            easy_positive_k: easyPositiveK,
            boundary_m: boundaryM,
            others_p: othersP,
          },
        });
      } catch (samplingErr) {
        // Sampling failed but model was created — navigate to model page with failure info
        const errorMessage =
          samplingErr instanceof Error ? samplingErr.message : String(samplingErr);
        onSuccess(model.id, { samplingFailed: true, error: errorMessage });
        return;
      }

      onSuccess(model.id);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      isSubmitting = false;
    }
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === e.currentTarget) {
      onClose();
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      onClose();
    }
  }
</script>

{#if open}
  <!-- Backdrop -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    onclick={handleBackdropClick}
    onkeydown={handleKeydown}
  >
    <!-- Dialog panel -->
    <div
      class="relative w-full max-w-lg rounded-xl border border-stone-200 bg-surface-card shadow-xl dark:border-stone-700"
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-model-dialog-title"
    >
      <!-- Header -->
      <div class="flex items-center justify-between border-b border-stone-100 px-6 py-4 dark:border-stone-800">
        <h2
          id="create-model-dialog-title"
          class="text-base font-semibold text-stone-900 dark:text-stone-100"
        >
          {m.models_train_from_search_title()}
        </h2>
        <button
          type="button"
          aria-label={m.models_train_from_search_close_aria()}
          class="rounded-md p-1 text-stone-400 transition-colors hover:text-stone-700 dark:hover:text-stone-300"
          onclick={onClose}
        >
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Body -->
      <form
        class="space-y-5 px-6 py-5"
        onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}
      >
        <!-- Target species (read-only) -->
        <div>
          <div class="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300">
            {m.models_train_target_species_label()}
          </div>
          <div class="rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 dark:border-stone-700 dark:bg-stone-800">
            <p class="text-sm font-medium text-stone-800 dark:text-stone-200">
              {formatSpeciesName(speciesConfig.common_name, speciesConfig.scientific_name)}
            </p>
          </div>
        </div>

        <!-- Model name -->
        <div>
          <label
            for="create-model-name"
            class="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300"
          >
            {m.models_train_model_name_label()}
          </label>
          <input
            id="create-model-name"
            type="text"
            bind:value={modelName}
            disabled={isSubmitting}
            class="w-full rounded-lg border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 shadow-sm
                   outline-none ring-primary-500 placeholder:text-stone-400
                   focus:border-primary-500 focus:ring-2
                   disabled:opacity-50
                   dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
            placeholder={m.models_train_model_name_placeholder()}
          />
        </div>

        <!-- Advanced settings (collapsible) -->
        <div>
          <button
            type="button"
            class="flex w-full items-center gap-1.5 text-sm font-medium text-stone-600 transition-colors hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-200"
            onclick={() => { showAdvanced = !showAdvanced; }}
          >
            <svg
              class="h-4 w-4 shrink-0 transition-transform duration-200 {showAdvanced ? 'rotate-90' : ''}"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
            </svg>
            {m.models_train_advanced_settings()}
          </button>

          {#if showAdvanced}
            <div class="mt-3 space-y-4 rounded-lg border border-stone-100 bg-stone-50 p-4 dark:border-stone-800 dark:bg-stone-800/50">

              <!-- easy_positive_k -->
              <div>
                <label
                  for="easy-positive-k"
                  class="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300"
                >
                  {m.models_train_obvious_matches_label()}
                  <span class="ml-1 font-mono text-xs text-stone-400">({easyPositiveK})</span>
                </label>
                <input
                  id="easy-positive-k"
                  type="range"
                  bind:value={easyPositiveK}
                  min="1"
                  max="50"
                  step="1"
                  disabled={isSubmitting}
                  class="w-full accent-primary-600 disabled:opacity-50"
                />
                <p class="mt-0.5 text-xs text-stone-400">
                  {m.models_train_obvious_matches_hint()}
                </p>
              </div>

              <!-- boundary_m -->
              <div>
                <label
                  for="boundary-m"
                  class="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300"
                >
                  {m.models_train_borderline_matches_label()}
                  <span class="ml-1 font-mono text-xs text-stone-400">({boundaryM})</span>
                </label>
                <input
                  id="boundary-m"
                  type="range"
                  bind:value={boundaryM}
                  min="1"
                  max="100"
                  step="1"
                  disabled={isSubmitting}
                  class="w-full accent-primary-600 disabled:opacity-50"
                />
                <p class="mt-0.5 text-xs text-stone-400">
                  {m.models_train_borderline_matches_hint()}
                </p>
              </div>

              <!-- others_p -->
              <div>
                <label
                  for="others-p"
                  class="mb-1 block text-sm font-medium text-stone-700 dark:text-stone-300"
                >
                  {m.models_train_background_samples_label()}
                  <span class="ml-1 font-mono text-xs text-stone-400">({othersP})</span>
                </label>
                <input
                  id="others-p"
                  type="range"
                  bind:value={othersP}
                  min="1"
                  max="200"
                  step="1"
                  disabled={isSubmitting}
                  class="w-full accent-primary-600 disabled:opacity-50"
                />
                <p class="mt-0.5 text-xs text-stone-400">
                  {m.models_train_background_samples_hint()}
                </p>
              </div>
            </div>
          {/if}
        </div>

        <!-- Error message -->
        {#if error}
          <div class="rounded-md border border-danger/30 bg-danger-light px-3 py-2 text-sm text-danger">
            {error}
          </div>
        {/if}
      </form>

      <!-- Footer -->
      <div class="flex items-center justify-end gap-2 border-t border-stone-100 px-6 py-4 dark:border-stone-800">
        <button
          type="button"
          class="rounded-lg border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700
                 transition-colors hover:bg-stone-50 disabled:opacity-50
                 dark:border-stone-600 dark:hover:bg-stone-700 dark:text-stone-300"
          disabled={isSubmitting}
          onclick={onClose}
        >
          {m.models_train_cancel()}
        </button>
        <button
          type="button"
          class="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white
                 shadow-sm transition-colors hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2
                 disabled:cursor-not-allowed disabled:opacity-50
                 dark:bg-primary-500 dark:hover:bg-primary-400"
          disabled={isSubmitting || !modelName.trim()}
          onclick={handleSubmit}
        >
          {#if isSubmitting}
            <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            {m.models_train_creating()}
          {:else}
            {m.models_train_create_and_sample()}
          {/if}
        </button>
      </div>
    </div>
  </div>
{/if}
