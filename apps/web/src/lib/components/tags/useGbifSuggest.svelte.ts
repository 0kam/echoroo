/**
 * useGbifSuggest — Svelte 5 runes hook for the debounced GBIF taxon lookup
 * used by the tag create form.
 *
 * Extracted from the tag settings page. Owns the suggestion list, the loading
 * flag, and the debounce timer. The timer is cleared on component destroy so a
 * pending lookup cannot fire after the form unmounts (the original page never
 * cleaned this up).
 *
 * Queries shorter than {@link MIN_GBIF_QUERY_LENGTH} are ignored (suggestions
 * cleared), matching the original guard.
 */
import { onDestroy } from 'svelte';
import { fetchGBIFSuggestions } from '$lib/api/tags';
import type { GBIFSuggestion } from '$lib/types/tag';

/** Minimum query length before a GBIF lookup is issued. */
export const MIN_GBIF_QUERY_LENGTH = 2;

/** Debounce delay (ms) before firing the GBIF lookup. */
export const GBIF_DEBOUNCE_MS = 300;

/**
 * Pure guard: whether a query string is long enough to trigger a lookup.
 * Extracted so it can be unit-tested without a component instance.
 */
export function shouldSearchGbif(query: string): boolean {
  return !!query && query.length >= MIN_GBIF_QUERY_LENGTH;
}

export interface GbifSuggestHandle {
  /** Current suggestion list (empty when idle / query too short). */
  readonly suggestions: GBIFSuggestion[];
  /** Whether a lookup is in flight. */
  readonly isLoading: boolean;
  /** Debounced lookup for the given query. */
  search: (query: string) => void;
  /** Clear the current suggestion list (e.g. after applying one). */
  clear: () => void;
}

/**
 * @param getProjectId Getter for the current project id. A getter (rather than
 * a plain string) keeps the lookup reactive to route changes and avoids
 * capturing a stale initial value.
 */
export function useGbifSuggest(getProjectId: () => string): GbifSuggestHandle {
  let suggestions = $state<GBIFSuggestion[]>([]);
  let isLoading = $state(false);
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function search(query: string) {
    if (!shouldSearchGbif(query)) {
      suggestions = [];
      return;
    }

    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      isLoading = true;
      try {
        suggestions = await fetchGBIFSuggestions(getProjectId(), query);
      } catch {
        suggestions = [];
      } finally {
        isLoading = false;
      }
    }, GBIF_DEBOUNCE_MS);
  }

  function clear() {
    suggestions = [];
  }

  // Move the debounce timer cleanup WITH the hook: clear any pending lookup on
  // destroy so it cannot resolve against an unmounted form.
  onDestroy(() => {
    if (debounceTimer) clearTimeout(debounceTimer);
  });

  return {
    get suggestions() {
      return suggestions;
    },
    get isLoading() {
      return isLoading;
    },
    search,
    clear,
  };
}
