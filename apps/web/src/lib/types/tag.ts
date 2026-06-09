/**
 * TypeScript type definitions for project tag management.
 *
 * Tags are shared by detection review, search/model workflows, species
 * pickers, and tag CRUD. They are intentionally separate from the removed
 * legacy annotation workflow.
 */

/** Tag classification category. */
export type TagCategory = 'species' | 'sound_type' | 'quality';

/** Tag entity used to label species, sound types, and quality markers. */
export interface Tag {
  /** Unique identifier. */
  id: string;
  /** Project this tag belongs to. */
  project_id: string;
  /** Parent tag identifier for hierarchical taxonomies. */
  parent_id?: string | null;
  /** Human-readable tag name. */
  name: string;
  /** Classification category. */
  category: TagCategory;
  /** GBIF backbone taxon key (species tags only). */
  gbif_taxon_key?: number | null;
  /** Scientific name (species tags only). */
  scientific_name?: string | null;
  /** Common / vernacular name (species tags only) - English default. */
  common_name?: string | null;
  /**
   * Locale-resolved vernacular name.
   *
   * Backend resolves this against the request's `locale` query parameter.
   * Null when no vernacular entry is available for the active locale.
   */
  vernacular_name?: string | null;
  /** Global taxon identifier linking this tag to the taxa table. */
  taxon_id?: string | null;
  /** ISO 8601 creation timestamp. */
  created_at: string;
  /** ISO 8601 last-update timestamp. */
  updated_at: string;
}

/** Tag with child tags and usage statistics. */
export interface TagDetail extends Tag {
  /** Direct child tags in the hierarchy. */
  children: Tag[];
  /** Number of annotations that reference this tag. */
  usage_count: number;
}

/** Request body to create a new tag. */
export interface TagCreate {
  /** Human-readable tag name. */
  name: string;
  /** Classification category. */
  category: TagCategory;
  /** Parent tag identifier for hierarchical taxonomies. */
  parent_id?: string;
  /** GBIF backbone taxon key (species tags only). */
  gbif_taxon_key?: number;
  /** Scientific name (species tags only). */
  scientific_name?: string;
  /** Common / vernacular name (species tags only). */
  common_name?: string;
}

/** Request body to partially update an existing tag. */
export interface TagUpdate {
  /** Updated human-readable name. */
  name?: string;
  /** Updated parent identifier; pass null to detach from hierarchy. */
  parent_id?: string | null;
  /** Updated common / vernacular name. */
  common_name?: string;
}

/** Paginated list of tags. */
export interface TagListResponse {
  /** Tag records for the current page. */
  items: Tag[];
  /** Total number of matching tags. */
  total: number;
  /** Current page number (1-indexed). */
  page: number;
  /** Number of items per page. */
  page_size: number;
  /** Total number of pages. */
  pages: number;
}

/** Taxon suggestion returned by the GBIF name-lookup API. */
export interface GBIFSuggestion {
  /** GBIF backbone taxon key. */
  key: number;
  /** Canonical (uninominal / binominal) name without authorship. */
  canonical_name: string;
  /** Full scientific name including authorship. */
  scientific_name: string;
  /** Taxonomic rank (e.g. "SPECIES", "GENUS"). */
  rank: string;
  /** Kingdom name. */
  kingdom?: string;
  /** Phylum name. */
  phylum?: string;
  /** Class name. */
  class_name?: string;
  /** Order name. */
  order?: string;
  /** Family name. */
  family?: string;
}

/** Tag paired with its usage count, used in statistics responses. */
export interface TagStatistic {
  /** The tag entity. */
  tag: Tag;
  /** Number of annotations that reference this tag. */
  usage_count: number;
}

/** Query parameters for listing tags. */
export interface TagListParams {
  /** Filter by tag category. */
  category?: TagCategory;
  /** Search term matched against name and scientific name. */
  search?: string;
  /** Page number (1-indexed). */
  page?: number;
  /** Number of items per page. */
  page_size?: number;
}
