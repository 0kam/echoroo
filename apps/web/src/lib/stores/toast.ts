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
  };
}

export const toasts = createToastStore();
