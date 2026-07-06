/**
 * Runes hook: poll a custom model's status while it is training.
 *
 * Extracted verbatim from the models page. Owns the polling timer together
 * with its cleanup so the interval can never leak: `stopPolling()` clears it,
 * `onDestroy` clears it on unmount, and the effect clears it whenever the
 * model leaves the `training` state.
 *
 * Cadence is 3s. Failure handling (W4-3 PR-2): consecutive fetch failures are
 * tolerated up to `MAX_POLL_FAILURES`, after which polling stops and a single
 * `toastError` is surfaced (not one per tick). The counter resets on any
 * successful fetch.
 */

import { onDestroy } from 'svelte';
import { getCustomModelStatus } from '$lib/api/custom-models';
import { toastError } from '$lib/stores/toast';
import * as m from '$lib/paraglide/messages';
import type { CustomModel } from '$lib/types/custom-model';

// Give up after this many CONSECUTIVE failed status fetches so a persistent
// backend/network fault does not poll forever in the background.
const MAX_POLL_FAILURES = 5;

export function useModelPolling(opts: {
  projectId: () => string;
  model: () => CustomModel | null;
  onComplete: (modelId: string) => void;
}) {
  let pollingInterval = $state<ReturnType<typeof setInterval> | null>(null);
  let polledModel = $state<CustomModel | null>(null);
  let pollFailureCount = 0;

  function stopPolling() {
    if (pollingInterval !== null) {
      clearInterval(pollingInterval);
      pollingInterval = null;
    }
    pollFailureCount = 0;
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
            pollFailureCount = 0;
            polledModel = updated;
            if (updated.status !== 'training') {
              stopPolling();
              // Invalidate list + detail so both refresh
              opts.onComplete(model.id);
            }
          } catch (err) {
            // Tolerate transient failures, but give up after a bounded number
            // of CONSECUTIVE errors and surface a single toast (not per tick).
            console.warn('Model status polling error:', err);
            pollFailureCount += 1;
            if (pollFailureCount >= MAX_POLL_FAILURES) {
              stopPolling();
              toastError(err, m.models_polling_stopped());
            }
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
