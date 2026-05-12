import { writable } from 'svelte/store';
import { generateId } from '$lib/utils/id';

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
