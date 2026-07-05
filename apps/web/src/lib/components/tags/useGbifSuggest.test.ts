import { describe, expect, it } from 'vitest';
import {
  GBIF_DEBOUNCE_MS,
  MIN_GBIF_QUERY_LENGTH,
  shouldSearchGbif,
} from './useGbifSuggest.svelte';

/**
 * Pure guard extracted from the GBIF suggest hook. It decides whether a query
 * string is long enough to warrant a lookup; the original page cleared the
 * suggestion list for empty / too-short queries instead of hitting the API.
 */
describe('shouldSearchGbif', () => {
  it('returns false for an empty string', () => {
    expect(shouldSearchGbif('')).toBe(false);
  });

  it('returns false for a single character (below the minimum)', () => {
    expect(shouldSearchGbif('a')).toBe(false);
  });

  it('returns true once the query reaches the minimum length', () => {
    expect(shouldSearchGbif('ab')).toBe(true);
  });

  it('returns true for longer queries', () => {
    expect(shouldSearchGbif('Turdus')).toBe(true);
  });

  it('exposes sane debounce / minimum-length constants', () => {
    expect(MIN_GBIF_QUERY_LENGTH).toBe(2);
    expect(GBIF_DEBOUNCE_MS).toBe(300);
  });
});
