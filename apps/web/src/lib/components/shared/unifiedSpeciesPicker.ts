/**
 * Pure helpers backing {@link UnifiedSpeciesPicker}.
 *
 * Kept out of the `.svelte` file so the dedup + canonical-result-construction
 * logic can be unit-tested without a component harness. The component imports
 * these and only owns the reactive state, debouncing, and rendering.
 */

import type { Tag } from '$lib/types/tag';
import type { GBIFSpeciesResult, TaxonSearchResult } from '$lib/types/taxon';
import type { SpeciesPickerResult } from '$lib/types/species-picker';
import { displayCommonName } from '$lib/utils/speciesFormatters';

/**
 * Normalize a name for case-insensitive, whitespace-insensitive comparison.
 *
 * Applies Unicode NFKC (folds full-width characters / compatibility forms),
 * collapses any run of whitespace (incl. full-width / irregular spaces) to a
 * single ASCII space, then trims and lower-cases. This lets cross-source
 * duplicates (taxon vs GBIF) dedupe even when one side carries odd whitespace.
 * Pure function.
 */
export function norm(value: string): string {
  return value
    .normalize('NFKC')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

/**
 * Resolve the common name to display/emit for a GBIF result under `locale`.
 *
 * The backend's `gbif-search` `vernacular_name` is its best match but is
 * English-biased, while `vernacular_names` carries every locale (and is
 * live-enriched with the requested locale when it is non-`en`). To keep a
 * locale name from being shadowed by an English best match, the precedence is:
 *   1. `vernacular_names` entry whose `language === locale`
 *   2. `vernacular_name` (backend best match)
 *   3. `vernacular_names` English entry
 *   4. null
 * Pure function so display, emitted `common_name`, and matching all agree.
 */
export function resolveGbifCommonName(
  gbif: GBIFSpeciesResult,
  locale: string,
): string | null {
  const all = gbif.vernacular_names;
  const byLocale = all?.find((vn) => vn.language === locale);
  if (byLocale) return byLocale.name;
  if (gbif.vernacular_name) return gbif.vernacular_name;
  const en = all?.find((vn) => vn.language === 'en');
  if (en) return en.name;
  return null;
}

/**
 * Whether a result key (a normalized scientific name) is already present in
 * `addedKeys`. Use {@link norm} on the row's scientific/canonical name before
 * calling so comparison is case-insensitive and whitespace-insensitive.
 *
 * Authoritative grey-out signal across all three sources (tag/taxon/gbif),
 * because tag-less picks (taxon/GBIF/custom) carry a null `tag_id` and so can't
 * be caught by the legacy `addedTagIds` id-based check.
 */
export function isAdded(
  scientificName: string,
  addedKeys: Set<string>,
): boolean {
  return addedKeys.has(norm(scientificName));
}

/** Scientific name backing a tag (falls back to the bare tag name). */
function tagScientificName(tag: Tag): string {
  return tag.scientific_name ?? tag.name;
}

/**
 * Drop taxa whose scientific name already appears among the project tags.
 *
 * Mirrors the dedup that `SpeciesSelector.svelte` performed so the unified
 * picker never lists the same species under both "Project" and "Species
 * database" sections.
 */
export function dedupTaxa(
  taxa: TaxonSearchResult[],
  tags: Tag[],
): TaxonSearchResult[] {
  const tagNames = new Set(tags.map((t) => norm(tagScientificName(t))));
  return taxa.filter((t) => !tagNames.has(norm(t.scientific_name)));
}

/**
 * Drop GBIF results already covered by a project tag or a local taxon.
 *
 * Comparison is against each GBIF row's `canonical_name` so the live-search
 * section only surfaces species that are genuinely new.
 */
export function dedupGbif(
  gbif: GBIFSpeciesResult[],
  tags: Tag[],
  taxa: TaxonSearchResult[],
): GBIFSpeciesResult[] {
  const existing = new Set<string>([
    ...tags.map((t) => norm(tagScientificName(t))),
    ...taxa.map((t) => norm(t.scientific_name)),
  ]);
  return gbif.filter((g) => !existing.has(norm(g.canonical_name)));
}

/**
 * Find a project tag whose scientific name matches `scientificName`.
 *
 * Used to "promote" a taxon / GBIF pick to a `source: 'tag'` result when an
 * existing project tag already represents that species, so downstream callers
 * reuse the tag instead of re-creating it.
 */
export function findMatchingTag(
  scientificName: string,
  tags: Tag[],
): Tag | null {
  const target = norm(scientificName);
  return tags.find((t) => norm(tagScientificName(t)) === target) ?? null;
}

/** Build a canonical result from a project tag pick. */
export function resultFromTag(tag: Tag): SpeciesPickerResult {
  return {
    source: 'tag',
    tag_id: tag.id,
    taxon_id: tag.taxon_id ?? null,
    gbif_key: tag.gbif_taxon_key ?? null,
    scientific_name: tagScientificName(tag),
    common_name: displayCommonName(tag),
  };
}

/**
 * Build a canonical result from a local-taxon pick.
 *
 * When a project tag already represents the same species the result is
 * promoted to `source: 'tag'` so the caller reuses the existing tag.
 */
export function resultFromTaxon(
  taxon: TaxonSearchResult,
  tags: Tag[],
): SpeciesPickerResult {
  const match = findMatchingTag(taxon.scientific_name, tags);
  if (match) return resultFromTag(match);
  return {
    source: 'taxon',
    tag_id: null,
    taxon_id: taxon.id,
    gbif_key: taxon.gbif_taxon_key ?? null,
    scientific_name: taxon.scientific_name,
    common_name: taxon.common_name,
  };
}

/**
 * Build a canonical result from a live-GBIF pick.
 *
 * Promotes to `source: 'tag'` when a project tag already matches; otherwise
 * the result carries only the GBIF key (no local taxon exists yet — palette
 * call sites resolve it to a `taxon_id` via `createTaxonFromGbif`).
 */
export function resultFromGbif(
  gbif: GBIFSpeciesResult,
  tags: Tag[],
  locale: string,
): SpeciesPickerResult {
  const match = findMatchingTag(gbif.canonical_name, tags);
  if (match) return resultFromTag(match);
  return {
    source: 'gbif',
    tag_id: null,
    taxon_id: null,
    gbif_key: gbif.gbif_key,
    scientific_name: gbif.canonical_name,
    common_name: resolveGbifCommonName(gbif, locale),
    // Carry the language-tagged names through so a later materialise call can
    // persist the locale vernacular (e.g. 和名) under the right locale.
    vernacular_names: gbif.vernacular_names,
  };
}

/** Build a canonical result for a free-text custom species entry. */
export function resultFromCustom(query: string): SpeciesPickerResult {
  return {
    source: 'custom',
    tag_id: null,
    taxon_id: null,
    gbif_key: null,
    scientific_name: query.trim(),
    common_name: null,
  };
}

/**
 * Whether the (trimmed) query already exactly matches any known name across
 * the three sources. Used to decide whether to offer the "add custom" row.
 */
export function hasExactMatch(
  query: string,
  tags: Tag[],
  taxa: TaxonSearchResult[],
  gbif: GBIFSpeciesResult[],
  locale: string,
): boolean {
  const q = norm(query);
  if (q.length === 0) return false;
  const tagHit = tags.some(
    (t) => norm(tagScientificName(t)) === q || norm(t.name) === q,
  );
  const taxonHit = taxa.some(
    (t) =>
      norm(t.scientific_name) === q ||
      (t.common_name != null && norm(t.common_name) === q),
  );
  const gbifHit = gbif.some((g) => {
    const common = resolveGbifCommonName(g, locale);
    return norm(g.canonical_name) === q || (common != null && norm(common) === q);
  });
  return tagHit || taxonHit || gbifHit;
}
