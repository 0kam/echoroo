/**
 * Shared types for the unified species picker.
 *
 * The {@link UnifiedSpeciesPicker} merges three search sources — project tags,
 * the local taxon database, and the live GBIF backbone — behind a single
 * canonical result shape. Call sites never see the source-specific row types
 * (Tag / TaxonSearchResult / GBIFSpeciesResult); they only receive a
 * {@link SpeciesPickerResult} and map it onto whatever their own model needs.
 */

/** Which search source produced a given pick. */
export type SpeciesPickerSource = 'tag' | 'taxon' | 'gbif' | 'custom';

/**
 * Behavioural mode for the picker.
 *
 * - `add-to-list`   — multi-add panel (search reference sounds): project tags +
 *   taxa + GBIF + optional custom entry; stays open after a pick and greys out
 *   already-added rows.
 * - `palette-search`— dropdown that grows an annotation-set palette: taxa +
 *   GBIF only; a single pick at a time.
 * - `tag-select`    — chip-based selector over a project's available tags
 *   (annotation task workspace): local filter + optional GBIF.
 */
export type SpeciesPickerMode = 'add-to-list' | 'palette-search' | 'tag-select';

/**
 * Canonical result emitted by the picker for every pick.
 *
 * Exactly which identifier fields are populated depends on {@link source}:
 * - `tag`    → `tag_id` set; `taxon_id` / `gbif_key` carried through from the tag
 * - `taxon`  → `taxon_id` set (the global taxa PK)
 * - `gbif`   → `gbif_key` set (no local taxon exists yet)
 * - `custom` → no identifiers; free-text scientific name only
 */
export interface SpeciesPickerResult {
  /** Source that produced this pick. */
  source: SpeciesPickerSource;
  /** Project-scoped tag PK; only set when `source === 'tag'`. */
  tag_id: string | null;
  /**
   * Global taxa PK. Set when `source === 'taxon'`, or carried from a tag's
   * `taxon_id` when `source === 'tag'` and the tag is linked to a taxon.
   */
  taxon_id: string | null;
  /** GBIF backbone taxon key; set when `source === 'gbif'` (or carried from a tag). */
  gbif_key: number | null;
  /** Canonical scientific name of the pick. */
  scientific_name: string;
  /** Locale-resolved common name, or null when none is available. */
  common_name: string | null;
  /**
   * Language-tagged vernacular names carried through from a GBIF pick, so a
   * materialise call (`createTaxonFromGbif`) can persist them under the right
   * locale (e.g. 和名). Only populated when `source === 'gbif'`; null otherwise.
   */
  vernacular_names?: Array<{ name: string; language: string; source?: string }> | null;
}
