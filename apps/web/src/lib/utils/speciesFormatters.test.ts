import { describe, it, expect } from 'vitest';
import { displayCommonName, displaySpeciesName, formatSpeciesName } from './speciesFormatters';

describe('formatSpeciesName', () => {
  it('combines distinct common and scientific names', () => {
    expect(formatSpeciesName('European Robin', 'Erithacus rubecula')).toBe(
      'European Robin (Erithacus rubecula)',
    );
  });

  it('collapses to scientific name when common equals scientific (case-insensitive)', () => {
    expect(formatSpeciesName('Erithacus rubecula', 'Erithacus rubecula')).toBe(
      'Erithacus rubecula',
    );
    expect(formatSpeciesName('erithacus RUBECULA', 'Erithacus rubecula')).toBe(
      'Erithacus rubecula',
    );
  });

  it('returns scientific name alone when common is missing', () => {
    expect(formatSpeciesName(null, 'Erithacus rubecula')).toBe('Erithacus rubecula');
    expect(formatSpeciesName('   ', 'Erithacus rubecula')).toBe('Erithacus rubecula');
    expect(formatSpeciesName(undefined, 'Erithacus rubecula')).toBe('Erithacus rubecula');
  });

  it('returns common name alone when scientific is missing', () => {
    expect(formatSpeciesName('European Robin', null)).toBe('European Robin');
    expect(formatSpeciesName('European Robin', '  ')).toBe('European Robin');
  });

  it('returns a safe non-empty fallback when both are missing', () => {
    expect(formatSpeciesName(null, null)).toBe('Unidentified');
    expect(formatSpeciesName('', '')).toBe('Unidentified');
    expect(formatSpeciesName(null, undefined, 'Unknown species')).toBe('Unknown species');
  });

  it('never returns an empty string even when the fallback is empty/whitespace', () => {
    // Default fallback applies when omitted.
    expect(formatSpeciesName(null, null)).toBe('Unidentified');
    // An empty or whitespace-only fallback degrades to the placeholder rather
    // than yielding an empty string.
    expect(formatSpeciesName(null, null, '')).toBe('Unidentified');
    expect(formatSpeciesName('', '   ', '   ')).toBe('Unidentified');
    // A provided non-empty fallback is still honoured when both names are empty.
    expect(formatSpeciesName('', '   ', 'No species')).toBe('No species');
  });

  it('trims surrounding whitespace before formatting', () => {
    expect(formatSpeciesName('  European Robin ', ' Erithacus rubecula ')).toBe(
      'European Robin (Erithacus rubecula)',
    );
  });
});

describe('displayCommonName', () => {
  it('prefers vernacular_name, then common_name, then name', () => {
    expect(
      displayCommonName({ vernacular_name: 'コマドリ', common_name: 'Robin', name: 'tag' }),
    ).toBe('コマドリ');
    expect(displayCommonName({ common_name: 'Robin', name: 'tag' })).toBe('Robin');
    expect(displayCommonName({ name: 'tag' })).toBe('tag');
  });

  it('returns null when no candidate carries text', () => {
    expect(displayCommonName({ name: '   ' })).toBeNull();
    expect(displayCommonName(null)).toBeNull();
  });
});

describe('displaySpeciesName', () => {
  it('renders common (scientific) for a Tag-like input', () => {
    expect(
      displaySpeciesName({ vernacular_name: 'コマドリ', scientific_name: 'Erithacus rubecula' }),
    ).toBe('コマドリ (Erithacus rubecula)');
  });

  it('falls back to scientific name when no common name resolves', () => {
    expect(displaySpeciesName({ scientific_name: 'Erithacus rubecula' })).toBe(
      'Erithacus rubecula',
    );
  });

  it('collapses duplicate common/scientific values', () => {
    expect(
      displaySpeciesName({ common_name: 'Erithacus rubecula', scientific_name: 'Erithacus rubecula' }),
    ).toBe('Erithacus rubecula');
  });

  it('uses the provided fallback when nothing is available', () => {
    expect(displaySpeciesName(null, 'Unidentified')).toBe('Unidentified');
  });
});
