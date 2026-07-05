import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { toasts, toastError } from './toast';
import { ApiError } from '$lib/api/client';
import * as m from '$lib/paraglide/messages';

/** Read the message of the most recently added toast. */
function lastToastMessage(): string | undefined {
  const list = get(toasts);
  return list[list.length - 1]?.message;
}

function lastToastType(): string | undefined {
  const list = get(toasts);
  return list[list.length - 1]?.type;
}

describe('toastError', () => {
  beforeEach(() => {
    // Drain any toasts left over from previous cases.
    for (const t of get(toasts)) toasts.remove(t.id);
  });

  it('prefers ApiError.detail when present', () => {
    toastError(new ApiError('Bad Request', 400, 'Dataset name already taken'));
    expect(lastToastMessage()).toBe('Dataset name already taken');
    expect(lastToastType()).toBe('error');
  });

  it('falls back to ApiError.message when detail is absent', () => {
    toastError(new ApiError('Something broke', 500));
    expect(lastToastMessage()).toBe('Something broke');
  });

  it('uses a plain Error message', () => {
    toastError(new Error('network down'));
    expect(lastToastMessage()).toBe('network down');
  });

  it('uses the explicit fallback for non-Error values', () => {
    toastError('weird', 'Custom fallback');
    expect(lastToastMessage()).toBe('Custom fallback');
  });

  it('uses the generic i18n message when nothing else resolves', () => {
    toastError(undefined);
    expect(lastToastMessage()).toBe(m.error_action_generic());
  });

  it('prefers the fallback over the generic message for empty Error messages', () => {
    toastError(new Error(''), 'Save failed');
    expect(lastToastMessage()).toBe('Save failed');
  });
});
