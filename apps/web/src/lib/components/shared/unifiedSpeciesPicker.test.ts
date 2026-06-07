import { describe, it, expect } from 'vitest';
import type { Tag } from '$lib/types/annotation';
import type { GBIFSpeciesResult, TaxonSearchResult } from '$lib/types/taxon';
import {
  dedupTaxa,
  dedupGbif,
  findMatchingTag,
  resultFromTag,
  resultFromTaxon,
  resultFromGbif,
  resultFromCustom,
  hasExactMatch,
  isAdded,
  norm,
  resolveGbifCommonName,
} from './unifiedSpeciesPicker';

// ------------------------------------------------------------------
// Fixtures
// ------------------------------------------------------------------

function makeTag(overrides: Partial<Tag> = {}): Tag {
  return {
    id: 'tag-1',
    project_id: 'proj-1',
    name: 'Robin',
    category: 'species',
    scientific_name: 'Erithacus rubecula',
    common_name: 'European Robin',
    vernacular_name: null,
    gbif_taxon_key: 111,
    taxon_id: 'taxon-1',
    created_at: '',
    updated_at: '',
    ...overrides,
  };
}

function makeTaxon(overrides: Partial<TaxonSearchResult> = {}): TaxonSearchResult {
  return {
    id: 'taxon-2',
    scientific_name: 'Turdus merula',
    gbif_taxon_key: 222,
    rank: 'SPECIES',
    is_non_biological: false,
    common_name: 'Common Blackbird',
    ...overrides,
  };
}

function makeGbif(overrides: Partial<GBIFSpeciesResult> = {}): GBIFSpeciesResult {
  return {
    gbif_key: 333,
    scientific_name: 'Parus major Linnaeus, 1758',
    canonical_name: 'Parus major',
    rank: 'SPECIES',
    vernacular_name: 'Great Tit',
    vernacular_names: null,
    kingdom: null,
    phylum: null,
    class_name: null,
    order: null,
    family: null,
    ...overrides,
  };
}

// ------------------------------------------------------------------
// dedupTaxa
// ------------------------------------------------------------------

describe('dedupTaxa', () => {
  it('removes taxa whose scientific name matches a project tag (case-insensitive)', () => {
    const tags = [makeTag({ scientific_name: 'Turdus merula' })];
    const taxa = [makeTaxon({ scientific_name: 'turdus MERULA' }), makeTaxon({ id: 't3', scientific_name: 'Sitta europaea' })];
    const result = dedupTaxa(taxa, tags);
    expect(result.map((t) => t.scientific_name)).toEqual(['Sitta europaea']);
  });

  it('falls back to tag.name when a tag has no scientific name', () => {
    const tags = [makeTag({ scientific_name: null, name: 'Sitta europaea' })];
    const taxa = [makeTaxon({ scientific_name: 'Sitta europaea' })];
    expect(dedupTaxa(taxa, tags)).toHaveLength(0);
  });

  it('keeps all taxa when there are no tags', () => {
    const taxa = [makeTaxon(), makeTaxon({ id: 't3', scientific_name: 'Sitta europaea' })];
    expect(dedupTaxa(taxa, [])).toHaveLength(2);
  });
});

// ------------------------------------------------------------------
// dedupGbif
// ------------------------------------------------------------------

describe('dedupGbif', () => {
  it('removes GBIF rows already covered by a project tag', () => {
    const tags = [makeTag({ scientific_name: 'Parus major' })];
    const gbif = [makeGbif({ canonical_name: 'parus major' }), makeGbif({ gbif_key: 444, canonical_name: 'Fringilla coelebs' })];
    const result = dedupGbif(gbif, tags, []);
    expect(result.map((g) => g.canonical_name)).toEqual(['Fringilla coelebs']);
  });

  it('removes GBIF rows already covered by a local taxon', () => {
    const taxa = [makeTaxon({ scientific_name: 'Parus major' })];
    const gbif = [makeGbif({ canonical_name: 'Parus major' })];
    expect(dedupGbif(gbif, [], taxa)).toHaveLength(0);
  });

  it('keeps novel GBIF rows', () => {
    const gbif = [makeGbif()];
    expect(dedupGbif(gbif, [makeTag()], [makeTaxon()])).toHaveLength(1);
  });
});

// ------------------------------------------------------------------
// findMatchingTag
// ------------------------------------------------------------------

describe('findMatchingTag', () => {
  it('matches by scientific name case-insensitively', () => {
    const tags = [makeTag({ scientific_name: 'Turdus merula' })];
    expect(findMatchingTag('turdus merula', tags)?.id).toBe('tag-1');
  });

  it('returns null when no tag matches', () => {
    expect(findMatchingTag('Nonexistent species', [makeTag()])).toBeNull();
  });
});

// ------------------------------------------------------------------
// resultFromTag
// ------------------------------------------------------------------

describe('resultFromTag', () => {
  it('carries tag_id, taxon_id and gbif_key through', () => {
    const r = resultFromTag(makeTag());
    expect(r).toMatchObject({
      source: 'tag',
      tag_id: 'tag-1',
      taxon_id: 'taxon-1',
      gbif_key: 111,
      scientific_name: 'Erithacus rubecula',
      common_name: 'European Robin',
    });
  });

  it('falls back to tag.name as scientific_name when scientific_name is null', () => {
    const r = resultFromTag(makeTag({ scientific_name: null, name: 'Mystery bird' }));
    expect(r.scientific_name).toBe('Mystery bird');
  });

  it('nulls out optional ids for a legacy tag', () => {
    const r = resultFromTag(makeTag({ taxon_id: null, gbif_taxon_key: null }));
    expect(r.taxon_id).toBeNull();
    expect(r.gbif_key).toBeNull();
  });
});

// ------------------------------------------------------------------
// resultFromTaxon
// ------------------------------------------------------------------

describe('resultFromTaxon', () => {
  it('returns a taxon result when no tag matches', () => {
    const r = resultFromTaxon(makeTaxon(), []);
    expect(r).toMatchObject({
      source: 'taxon',
      tag_id: null,
      taxon_id: 'taxon-2',
      gbif_key: 222,
      scientific_name: 'Turdus merula',
      common_name: 'Common Blackbird',
    });
  });

  it('promotes to a tag result when a project tag matches the scientific name', () => {
    const tags = [makeTag({ id: 'existing', scientific_name: 'Turdus merula' })];
    const r = resultFromTaxon(makeTaxon({ scientific_name: 'Turdus merula' }), tags);
    expect(r.source).toBe('tag');
    expect(r.tag_id).toBe('existing');
  });
});

// ------------------------------------------------------------------
// resultFromGbif
// ------------------------------------------------------------------

describe('resultFromGbif', () => {
  it('returns a gbif result (only gbif_key set) when no tag matches', () => {
    const r = resultFromGbif(makeGbif(), [], 'en');
    expect(r).toMatchObject({
      source: 'gbif',
      tag_id: null,
      taxon_id: null,
      gbif_key: 333,
      scientific_name: 'Parus major',
      common_name: 'Great Tit',
    });
  });

  it('promotes to a tag result when a project tag matches the canonical name', () => {
    const tags = [makeTag({ id: 'existing', scientific_name: 'Parus major' })];
    const r = resultFromGbif(makeGbif({ canonical_name: 'Parus major' }), tags, 'en');
    expect(r.source).toBe('tag');
    expect(r.tag_id).toBe('existing');
  });

  it('emits the locale-resolved common name when vernacular_name is absent', () => {
    const r = resultFromGbif(
      makeGbif({
        vernacular_name: null,
        vernacular_names: [
          { name: 'シジュウカラ', language: 'ja' },
          { name: 'Great Tit', language: 'en' },
        ],
      }),
      [],
      'ja',
    );
    expect(r.common_name).toBe('シジュウカラ');
  });
});

// ------------------------------------------------------------------
// resultFromCustom
// ------------------------------------------------------------------

describe('resultFromCustom', () => {
  it('trims the query and carries no identifiers', () => {
    const r = resultFromCustom('  Novel species  ');
    expect(r).toEqual({
      source: 'custom',
      tag_id: null,
      taxon_id: null,
      gbif_key: null,
      scientific_name: 'Novel species',
      common_name: null,
    });
  });
});

// ------------------------------------------------------------------
// hasExactMatch
// ------------------------------------------------------------------

// ------------------------------------------------------------------
// isAdded — authoritative grey-out across tag / taxon / gbif rows
// ------------------------------------------------------------------

describe('isAdded', () => {
  // A row key is the *normalized* scientific name (tag/taxon: scientific_name,
  // gbif: canonical_name). The call sites build addedKeys with `norm`.
  const addedKeys = new Set([norm('Turdus merula'), norm('Parus major')]);

  it('flags a tag row whose scientific name is in addedKeys', () => {
    const tag = makeTag({ scientific_name: 'Turdus merula' });
    expect(isAdded(tag.scientific_name ?? tag.name, addedKeys)).toBe(true);
  });

  it('flags a taxon row whose scientific name is in addedKeys', () => {
    const taxon = makeTaxon({ scientific_name: 'Turdus merula' });
    expect(isAdded(taxon.scientific_name, addedKeys)).toBe(true);
  });

  it('flags a gbif row whose canonical name is in addedKeys', () => {
    const gbif = makeGbif({ canonical_name: 'Parus major' });
    expect(isAdded(gbif.canonical_name, addedKeys)).toBe(true);
  });

  it('matches case-insensitively and ignores surrounding whitespace', () => {
    expect(isAdded('  turdus MERULA  ', addedKeys)).toBe(true);
  });

  it('does not flag a row whose name is absent from addedKeys', () => {
    const taxon = makeTaxon({ scientific_name: 'Sitta europaea' });
    expect(isAdded(taxon.scientific_name, addedKeys)).toBe(false);
  });

  it('treats an empty addedKeys set as nothing-added', () => {
    expect(isAdded('Turdus merula', new Set())).toBe(false);
  });

  it('uses tag.name as the key when a tag has no scientific name', () => {
    const tag = makeTag({ scientific_name: null, name: 'Sitta europaea' });
    const keys = new Set([norm('Sitta europaea')]);
    expect(isAdded(tag.scientific_name ?? tag.name, keys)).toBe(true);
  });
});

describe('hasExactMatch', () => {
  it('matches a tag scientific name', () => {
    expect(hasExactMatch('Erithacus rubecula', [makeTag()], [], [], 'en')).toBe(true);
  });

  it('matches a tag bare name', () => {
    expect(hasExactMatch('Robin', [makeTag()], [], [], 'en')).toBe(true);
  });

  it('matches a taxon common name case-insensitively', () => {
    expect(hasExactMatch('common blackbird', [], [makeTaxon()], [], 'en')).toBe(true);
  });

  it('matches a GBIF vernacular name', () => {
    expect(hasExactMatch('Great Tit', [], [], [makeGbif()], 'en')).toBe(true);
  });

  it('matches a GBIF locale-resolved vernacular name when vernacular_name is absent', () => {
    const gbif = makeGbif({
      vernacular_name: null,
      vernacular_names: [{ name: 'シジュウカラ', language: 'ja' }],
    });
    expect(hasExactMatch('シジュウカラ', [], [], [gbif], 'ja')).toBe(true);
  });

  it('returns false for an unknown query', () => {
    expect(hasExactMatch('Unknown', [makeTag()], [makeTaxon()], [makeGbif()], 'en')).toBe(false);
  });

  it('returns false for an empty query', () => {
    expect(hasExactMatch('   ', [makeTag()], [], [], 'en')).toBe(false);
  });
});

// ------------------------------------------------------------------
// norm — Unicode/whitespace normalization (fix F)
// ------------------------------------------------------------------

describe('norm', () => {
  it('trims and lower-cases', () => {
    expect(norm('  Turdus Merula  ')).toBe('turdus merula');
  });

  it('collapses a full-width (ideographic) space to a single ASCII space', () => {
    expect(norm('Turdus　merula')).toBe('turdus merula');
  });

  it('collapses runs of mixed whitespace to a single space', () => {
    expect(norm('Turdus   \t merula')).toBe('turdus merula');
  });

  it('applies NFKC so full-width latin folds to ASCII', () => {
    // Full-width "Ｐａｒｕｓ ｍａｊｏｒ" → "parus major".
    expect(norm('Ｐａｒｕｓ　ｍａｊｏｒ')).toBe('parus major');
  });

  it('lets cross-source duplicates with odd whitespace collapse', () => {
    expect(norm('Parus major')).toBe(norm('Parus　major'));
  });
});

// ------------------------------------------------------------------
// resolveGbifCommonName — ja → en → null fallback (fix D)
// ------------------------------------------------------------------

describe('resolveGbifCommonName', () => {
  it('prefers vernacular_name (backend best match) when present', () => {
    const gbif = makeGbif({
      vernacular_name: 'Great Tit',
      vernacular_names: [{ name: 'シジュウカラ', language: 'ja' }],
    });
    expect(resolveGbifCommonName(gbif, 'ja')).toBe('Great Tit');
  });

  it('falls back to vernacular_names[locale] when vernacular_name is null', () => {
    const gbif = makeGbif({
      vernacular_name: null,
      vernacular_names: [
        { name: 'シジュウカラ', language: 'ja' },
        { name: 'Great Tit', language: 'en' },
      ],
    });
    expect(resolveGbifCommonName(gbif, 'ja')).toBe('シジュウカラ');
  });

  it('falls back to English when the requested locale is missing', () => {
    const gbif = makeGbif({
      vernacular_name: null,
      vernacular_names: [{ name: 'Great Tit', language: 'en' }],
    });
    expect(resolveGbifCommonName(gbif, 'ja')).toBe('Great Tit');
  });

  it('returns null when no usable vernacular name exists', () => {
    const gbif = makeGbif({ vernacular_name: null, vernacular_names: null });
    expect(resolveGbifCommonName(gbif, 'ja')).toBeNull();
    const empty = makeGbif({ vernacular_name: null, vernacular_names: [] });
    expect(resolveGbifCommonName(empty, 'ja')).toBeNull();
    const otherOnly = makeGbif({
      vernacular_name: null,
      vernacular_names: [{ name: 'Kohlmeise', language: 'de' }],
    });
    expect(resolveGbifCommonName(otherOnly, 'ja')).toBeNull();
  });
});
