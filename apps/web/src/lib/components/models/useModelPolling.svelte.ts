/**
 * Runes hook: poll a custom model's status while it is training.
 *
 * Extracted verbatim from the models page. Owns the polling timer together
 * with its cleanup so the interval can never leak: `stopPolling()` clears it,
 * `onDestroy` clears it on unmount, and the effect clears it whenever the
 * model leaves the `training` state.
 *
 * Behaviour is intentionally unchanged (3s cadence, `console.warn` on error);
 * an error-UX follow-up PR will improve the failure handling.
 */

import { onDestroy } from 'svelte';
import { getCustomModelStatus } from '$lib/api/custom-models';
import type { CustomModel } from '$lib/types/custom-model';

export function useModelPolling(opts: {
  projectId: () => string;
  model: () => CustomModel | null;
  onComplete: (modelId: string) => void;
}) {
  let pollingInterval = $state<ReturnType<typeof setInterval> | null>(null);
  let polledModel = $state<CustomModel | null>(null);

  function stopPolling() {
    if (pollingInterval !== null) {
      clearInterval(pollingInterval);
      pollingInterval = null;
    }
  }

  onDestroy(() => {
    stopPolling();
  });

  // Start polling when a model is training
  $effect(() => {
    const model = opts.model();
    if (model?.status === 'training') {
      if (pollingInterval === null) {
        pollingInterval = setInterval(async () => {
          try {
            const updated = await getCustomModelStatus(opts.projectId(), model.id);
            polledModel = updated;
            if (updated.status !== 'training') {
              stopPolling();
              // Invalidate list + detail so both refresh
              opts.onComplete(model.id);
            }
          } catch (err) {
            console.warn('Model status polling error:', err);
          }
        }, 3000);
      }
    } else {
      stopPolling();
      polledModel = null;
    }
  });

  return {
    get polledModel() {
      return polledModel;
    },
    stopPolling,
    reset() {
      stopPolling();
      polledModel = null;
    },
  };
}
