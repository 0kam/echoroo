import { z } from "zod";

import * as schemas from "@/lib/schemas";

// ============================================================================
// Species Filter Types
// ============================================================================

export type SpeciesFilterType = z.infer<
  typeof schemas.SpeciesFilterTypeSchema
>;

export type SpeciesFilter = z.infer<typeof schemas.SpeciesFilterSchema>;

// ============================================================================
// Species Filter Application Types
// ============================================================================

export type SpeciesFilterApplicationStatus = z.infer<
  typeof schemas.SpeciesFilterApplicationStatusSchema
>;

export type SpeciesFilterApplication = z.infer<
  typeof schemas.SpeciesFilterApplicationSchema
>;

export type SpeciesFilterApplicationCreate = z.input<
  typeof schemas.SpeciesFilterApplicationCreateSchema
>;

export type SpeciesFilterApplicationProgress = z.infer<
  typeof schemas.SpeciesFilterApplicationProgressSchema
>;

// ============================================================================
// Excluded Species Summary
// ============================================================================

export type ExcludedSpeciesSummary = z.infer<
  typeof schemas.ExcludedSpeciesSummarySchema
>;

// ============================================================================
// Species Filter Result Item
// ============================================================================

export type SpeciesFilterResultItem = z.infer<
  typeof schemas.SpeciesFilterResultItemSchema
>;

// ============================================================================
// Species Filter Results
// ============================================================================

export type SpeciesFilterResults = z.infer<
  typeof schemas.SpeciesFilterResultsSchema
>;
