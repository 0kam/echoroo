/**
 * Taxon type definitions for global species taxonomy.
 */

/**
 * A vernacular (common) name entry for a taxon in a specific locale.
 */
export interface VernacularName {
  /** Unique identifier */
  id: string;
  /** BCP 47 locale code (e.g. "en", "ja") */
  locale: string;
  /** Vernacular name in the given locale */
  name: string;
  /** Source of this name entry (e.g. "gbif", "manual") */
  source: string;
  /** Whether this is the primary/preferred name for the locale */
  is_primary: boolean;
}

/**
 * Global taxon entity representing a species or higher-level taxonomic unit.
 */
export interface Taxon {
  /** Unique identifier */
  id: string;
  /** Accepted scientific name */
  scientific_name: string;
  /** GBIF backbone taxon key; null if not linked to GBIF */
  gbif_taxon_key: number | null;
  /** Taxonomic rank (e.g. "SPECIES", "GENUS"); null if unknown */
  rank: string | null;
  /** Whether this taxon represents a non-biological sound source */
  is_non_biological: boolean;
  /** ISO 8601 creation timestamp */
  created_at: string;
}

/**
 * Taxon with full GBIF metadata and vernacular names.
 */
export interface TaxonDetail extends Taxon {
  /** Raw GBIF metadata blob; null if not yet resolved */
  gbif_metadata: Record<string, unknown> | null;
  /** ISO 8601 timestamp when GBIF metadata was last resolved; null if never */
  gbif_resolved_at: string | null;
  /** Vernacular names across all locales */
  vernacular_names: VernacularName[];
  /** ISO 8601 last-update timestamp */
  updated_at: string;
}

/**
 * Paginated list of taxa.
 */
export interface TaxonListResponse {
  /** Taxon records for the current page */
  items: Taxon[];
  /** Total number of matching taxa */
  total: number;
  /** Current page number (1-indexed) */
  page: number;
  /** Number of items per page */
  page_size: number;
  /** Total number of pages */
  pages: number;
}

/**
 * Lightweight taxon result returned by the search endpoint.
 * Includes a resolved common name for the requested locale.
 */
export interface TaxonSearchResult {
  /** Unique identifier */
  id: string;
  /** Accepted scientific name */
  scientific_name: string;
  /** GBIF backbone taxon key; null if not linked to GBIF */
  gbif_taxon_key: number | null;
  /** Taxonomic rank (e.g. "SPECIES", "GENUS"); null if unknown */
  rank: string | null;
  /** Whether this taxon represents a non-biological sound source */
  is_non_biological: boolean;
  /** Primary common name for the requested locale; null if not available */
  common_name: string | null;
}
