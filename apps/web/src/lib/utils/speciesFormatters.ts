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
 * Return the full species label: "Common name (Scientific name)".
 *
 * If no common name can be resolved the scientific name (or the provided
 * `fallback`) is returned on its own.  If neither a common name nor a
 * scientific name is available the `fallback` is returned.
 */
export function displaySpeciesName(
  tag: TagLike | null | undefined,
  fallback: string = 'Unidentified',
): string {
  const common = displayCommonName(tag);
  const scientific = tag?.scientific_name?.trim() || null;

  if (common && scientific) return `${common} (${scientific})`;
  if (common) return common;
  if (scientific) return scientific;
  return fallback;
}
