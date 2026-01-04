"use client";

import { z } from "zod";

// ============================================================================
// Species Filter Type
// ============================================================================

export const SpeciesFilterTypeSchema = z.enum([
  "geographic",
  "occurrence",
  "custom",
]);

// ============================================================================
// Species Filter
// ============================================================================

export const SpeciesFilterSchema = z.object({
  uuid: z.string().uuid(),
  slug: z.string(),
  display_name: z.string(),
  provider: z.string(),
  version: z.string(),
  description: z.string().nullable(),
  filter_type: SpeciesFilterTypeSchema,
  default_threshold: z.number(),
  requires_location: z.boolean(),
  requires_date: z.boolean(),
  is_active: z.boolean(),
});

// ============================================================================
// Species Filter Application Status
// ============================================================================

export const SpeciesFilterApplicationStatusSchema = z.enum([
  "pending",
  "running",
  "completed",
  "failed",
  "cancelled",
]);

// ============================================================================
// Species Filter Application
// ============================================================================

export const SpeciesFilterApplicationSchema = z.object({
  uuid: z.string().uuid(),
  foundation_model_run_id: z.number().int().optional(),
  species_filter_id: z.number().int().optional(),
  species_filter: SpeciesFilterSchema.optional(),
  threshold: z.number(),
  apply_to_all_detections: z.boolean(),
  status: SpeciesFilterApplicationStatusSchema,
  progress: z.number(),
  total_detections: z.number().int().nullable(),
  filtered_detections: z.number().int().nullable(),
  excluded_detections: z.number().int().nullable(),
  applied_by_id: z.string().uuid().nullable().optional(),
  started_on: z.coerce.date().nullable(),
  completed_on: z.coerce.date().nullable(),
  error: z.any().nullable(),
});

// ============================================================================
// Species Filter Application Create
// ============================================================================

export const SpeciesFilterApplicationCreateSchema = z.object({
  filter_slug: z.string(),
  threshold: z.number().min(0).max(1),
  apply_to_all_detections: z.boolean().default(true),
});

// ============================================================================
// Species Filter Application Progress
// ============================================================================

export const SpeciesFilterApplicationProgressSchema = z.object({
  uuid: z.string().uuid(),
  status: SpeciesFilterApplicationStatusSchema,
  progress: z.number(),
  total_detections: z.number().int(),
  filtered_detections: z.number().int(),
  excluded_detections: z.number().int(),
});

// ============================================================================
// Excluded Species Summary
// ============================================================================

export const ExcludedSpeciesSummarySchema = z.object({
  species_name: z.string(),
  tag_id: z.number().int().nullable(),
  excluded_count: z.number().int(),
});

// ============================================================================
// Species Filter Result Item
// ============================================================================

export const SpeciesFilterResultItemSchema = z.object({
  gbif_taxon_key: z.string(),
  species_name: z.string().nullable(),
  common_name: z.string().nullable().optional(),
  is_included: z.boolean(),
  occurrence_probability: z.number().nullable(),
  detection_count: z.number().int(),
});

// ============================================================================
// Species Filter Results
// ============================================================================

export const SpeciesFilterResultsSchema = z.object({
  passed: z.array(SpeciesFilterResultItemSchema),
  excluded: z.array(SpeciesFilterResultItemSchema),
  total_passed: z.number().int(),
  total_excluded: z.number().int(),
});
