import { writable } from 'svelte/store';
import { generateId } from '$lib/utils/id';
import { ApiError } from '$lib/api/client';
import * as m from '$lib/paraglide/messages';

export interface Toast {
  id: string;
  message: string;
  type: 'success' | 'error' | 'warning' | 'info';
  duration?: number;
}

function createToastStore() {
  const { subscribe, update } = writable<Toast[]>([]);

  return {
    subscribe,
    add: (toast: Omit<Toast, 'id'>) => {
      const id = generateId();
      update(toasts => [...toasts, { ...toast, id }]);
      return id;
    },
    remove: (id: string) => {
      update(toasts => toasts.filter(t => t.id !== id));
    },
    success: (message: string) => {
      const id = generateId();
      update(toasts => [...toasts, { id, message, type: 'success' }]);
    },
    error: (message: string) => {
      const id = generateId();
      update(toasts => [...toasts, { id, message, type: 'error', duration: 8000 }]);
    },
    /**
     * Surface a non-fatal warning toast. Used by the permissions
     * demotion-race handler (spec/007 Phase 1.5 / AD-3) to inform the
     * user that the page may need to refresh because their project
     * access changed under them.
     */
    warning: (message: string) => {
      const id = generateId();
      update(toasts => [...toasts, { id, message, type: 'warning', duration: 6000 }]);
    },
  };
}

export const toasts = createToastStore();

/**
 * Surface an error as a toast, unwrapping an `ApiError` when present.
 *
 * Message resolution order:
 *   1. `ApiError.detail` (the backend's human-readable detail string)
 *   2. `ApiError.message` (or a plain `Error.message`)
 *   3. `fallbackMessage`
 *   4. the generic `error_action_generic` i18n string
 *
 * Used as the default handler for the global `MutationCache.onError`
 * fallback (see `$lib/api/query-client`) so any mutation that does not
 * opt out via `meta: { suppressErrorToast: true }` still gives the user
 * feedback when it fails.
 */
export function toastError(err: unknown, fallbackMessage?: string): void {
  let message: string | undefined;

  if (err instanceof ApiError) {
    message = err.detail || err.message || undefined;
  } else if (err instanceof Error) {
    message = err.message || undefined;
  }

  toasts.error(message ?? fallbackMessage ?? m.error_action_generic());
}
