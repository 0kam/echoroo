/**
 * Species name formatting helpers.
 *
 * Centralises the logic that turns a tag / species-like object into the
 * human-readable names shown in the UI so each surface renders consistently
 * across locales.
 *
 * The backend resolves a locale-specific `vernacular_name` per request.  When
 * no vernacular entry is available for the active locale the backend returns
 * `null`, in which case we fall back to the canonical English `common_name`
 * (used throughout legacy data) and finally to the tag's bare `name` field.
 */

/**
 * Minimal shape accepted by these helpers.
 *
 * Only the fields we inspect are declared.  Callers can pass any object that
 * structurally matches (tags, species summaries, palette entries, etc.).
 */
export interface TagLike {
  /** Raw tag name (legacy fallback when no taxon is linked) */
  name?: string | null;
  /** English common name stored on the tag itself */
  common_name?: string | null;
  /** Locale-resolved vernacular name supplied by the backend */
  vernacular_name?: string | null;
  /** Scientific (binomial) name */
  scientific_name?: string | null;
}

/**
 * Return the preferred common name for display.
 *
 * Preference order:
 * 1. `vernacular_name` — already resolved for the active locale
 * 2. `common_name` — English default
 * 3. `name` — raw tag label
 *
 * Returns `null` when every candidate is empty so callers can decide how to
 * render a species that has no human-readable label.
 */
export function displayCommonName(tag: TagLike | null | undefined): string | null {
  if (!tag) return null;
  const candidate = tag.vernacular_name ?? tag.common_name ?? tag.name ?? null;
  if (candidate == null) return null;
  const trimmed = candidate.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Placeholder shown when a species carries no human-readable label and the
 * caller supplies no usable fallback.  Centralised so every surface degrades to
 * the same non-empty text.
 */
export const UNIDENTIFIED_PLACEHOLDER = 'Unidentified';

/**
 * Combine an already-resolved common name and scientific name into the shared
 * "Common name (Scientific name)" label used across every species surface.
 *
 * This is the single source of truth for the "併記" (common + scientific
 * together) format.  Rules:
 * - Both present and distinct (case-insensitive, trimmed) → "common (scientific)"
 * - No common name, or common equals scientific → scientific alone
 * - No scientific name → common alone
 * - Neither present → the `fallback` (never an empty string)
 *
 * It never renders a duplicate such as "Robin (Robin)" and never returns an
 * empty string while any field carries text.
 */
export function formatSpeciesName(
  common: string | null | undefined,
  scientific: string | null | undefined,
  fallback: string = UNIDENTIFIED_PLACEHOLDER,
): string {
  const commonTrimmed = common?.trim() || null;
  const scientificTrimmed = scientific?.trim() || null;

  if (commonTrimmed && scientificTrimmed) {
    // Collapse to the scientific name alone when the two are identical so we
    // never render "X (X)". Comparison is case-insensitive.
    if (commonTrimmed.toLowerCase() === scientificTrimmed.toLowerCase()) {
      return scientificTrimmed;
    }
    return `${commonTrimmed} (${scientificTrimmed})`;
  }
  if (commonTrimmed) return commonTrimmed;
  if (scientificTrimmed) return scientificTrimmed;
  // Honour the "never empty" guarantee: an empty/whitespace-only fallback
  // degrades to the shared placeholder.
  return fallback.trim() || UNIDENTIFIED_PLACEHOLDER;
}

/**
 * Return the full species label: "Common name (Scientific name)".
 *
 * Delegates to {@link formatSpeciesName} after resolving the locale-preferred
 * common name, so Tag-like inputs get the same duplicate-collapse and fallback
 * behaviour as every other surface.
 */
export function displaySpeciesName(
  tag: TagLike | null | undefined,
  fallback: string = UNIDENTIFIED_PLACEHOLDER,
): string {
  return formatSpeciesName(displayCommonName(tag), tag?.scientific_name, fallback);
}
