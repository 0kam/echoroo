"use client";

import { z } from "zod";

import { ClipSchema } from "./clips";
import { ReferenceSoundSchema } from "./reference_sounds";
import { TagSchema } from "./tags";

// Distance metric type for similarity search
export const DistanceMetricSchema = z.enum(["cosine", "euclidean"]);
export type DistanceMetric = z.infer<typeof DistanceMetricSchema>;

// SearchSessionTargetTag schema - Target tag with shortcut key assignment
export const SearchSessionTargetTagSchema = z.object({
  tag_id: z.number().int(),
  tag: TagSchema,
  shortcut_key: z.number().int().min(1).max(9),
});

export type SearchSessionTargetTag = z.infer<typeof SearchSessionTargetTagSchema>;

// Sample type enum for Active Learning
export const SampleTypeSchema = z.enum([
  "easy_positive",
  "boundary",
  "others",
  "active_learning",
]);

export type SampleType = z.infer<typeof SampleTypeSchema>;

// Main SearchSession schema with Active Learning support
export const SearchSessionSchema = z.object({
  uuid: z.string().uuid(),
  name: z.string().nullable(),
  description: z.string().nullable().optional(),
  ml_project_uuid: z.string().uuid(),

  // Multi-tag support
  target_tags: z.array(SearchSessionTargetTagSchema).default([]),

  // Active Learning parameters
  easy_positive_k: z.number().int().default(5),
  boundary_n: z.number().int().default(200),
  boundary_m: z.number().int().default(10),
  others_p: z.number().int().default(20),
  current_iteration: z.number().int().default(0),
  distance_metric: DistanceMetricSchema.default("cosine"),

  // Status flags
  is_search_complete: z.boolean().default(false),

  // Progress counts
  total_results: z.number().int().default(0),
  labeled_count: z.number().int().default(0),
  unlabeled_count: z.number().int().default(0),
  negative_count: z.number().int().default(0),
  uncertain_count: z.number().int().default(0),
  skipped_count: z.number().int().default(0),

  // Per-tag counts (tag_id -> count)
  tag_counts: z.record(z.string(), z.number().int()).default({}),

  notes: z.string().nullable().optional(),
  reference_sounds: z.array(ReferenceSoundSchema).default([]),
  created_by_id: z.string().uuid().nullable().optional(),
  created_on: z.coerce.date().optional(),
});

export type SearchSession = z.infer<typeof SearchSessionSchema>;

// Create schema with Active Learning parameters
export const SearchSessionCreateSchema = z.object({
  name: z.string().max(255).nullable().optional(),
  description: z.string().max(2000).optional(),
  reference_sound_ids: z.array(z.string().uuid()).min(1, "At least one reference sound is required"),

  // Active Learning sampling parameters
  easy_positive_k: z.number().int().min(0).max(50).default(5),
  boundary_n: z.number().int().min(0).max(1000).default(200),
  boundary_m: z.number().int().min(0).max(100).default(10),
  others_p: z.number().int().min(0).max(200).default(20),
  distance_metric: DistanceMetricSchema.default("cosine"),

  notes: z.string().max(2000).optional(),
});

export type SearchSessionCreate = z.infer<typeof SearchSessionCreateSchema>;

// SearchResultLabelData schema - replaces SearchResultLabelUpdate
export const SearchResultLabelDataSchema = z.object({
  assigned_tag_id: z.number().int().nullable().optional(),
  is_negative: z.boolean().default(false),
  is_uncertain: z.boolean().default(false),
  is_skipped: z.boolean().default(false),
  notes: z.string().max(2000).optional(),
});

export type SearchResultLabelData = z.infer<typeof SearchResultLabelDataSchema>;

// SearchResult schema with Active Learning label fields
export const SearchResultSchema = z.object({
  uuid: z.string().uuid(),
  search_session_uuid: z.string().uuid(),
  clip_id: z.number().int().optional(), // Backend excludes this field
  clip: ClipSchema,
  similarity: z.number().min(0).max(1),
  rank: z.number().int().min(1),

  // Active Learning label fields
  assigned_tag_id: z.number().int().nullable().optional(),
  assigned_tag: TagSchema.nullable().optional(),
  is_negative: z.boolean().default(false),
  is_uncertain: z.boolean().default(false),
  is_skipped: z.boolean().default(false),

  // Sampling metadata
  sample_type: SampleTypeSchema.nullable().optional(),
  iteration_added: z.number().int().nullable().optional(),
  model_score: z.number().nullable().optional(),
  source_tag_id: z.number().int().nullable().optional(),
  source_tag: TagSchema.nullable().optional(),

  // User tracking
  labeled_at: z.coerce.date().nullable().optional(),
  labeled_by_id: z.string().uuid().nullable().optional(),
  notes: z.string().nullable().optional(),
});

export type SearchResult = z.infer<typeof SearchResultSchema>;

// Bulk label request schema with Active Learning labels
export const BulkLabelRequestSchema = z.object({
  result_uuids: z.array(z.string().uuid()).min(1).max(500),
  label_data: SearchResultLabelDataSchema,
});

export type BulkLabelRequest = z.infer<typeof BulkLabelRequestSchema>;

// Search progress schema with Active Learning fields
export const SearchProgressSchema = z.object({
  total: z.number().int(),
  labeled: z.number().int(),
  unlabeled: z.number().int(),
  negative: z.number().int(),
  uncertain: z.number().int(),
  skipped: z.number().int(),
  tag_counts: z.record(z.string(), z.number().int()).default({}),
  progress_percent: z.number().default(0),
});

export type SearchProgress = z.infer<typeof SearchProgressSchema>;

// Bulk curate request schema for exporting as references
export const BulkCurateRequestSchema = z.object({
  result_uuids: z.array(z.string().uuid()).min(1).max(500),
  assigned_tag_id: z.number().int(),
});

export type BulkCurateRequest = z.infer<typeof BulkCurateRequestSchema>;

// Tag score distribution schema for visualization
export const TagScoreDistributionSchema = z.object({
  tag_id: z.number().int(),
  tag_name: z.string(),
  iteration: z.number().int(),
  bin_counts: z.array(z.number().int()),
  bin_edges: z.array(z.number()),
  positive_count: z.number().int(),
  negative_count: z.number().int(),
  mean_score: z.number(),
});

export type TagScoreDistribution = z.infer<typeof TagScoreDistributionSchema>;

export const ScoreDistributionResponseSchema = z.object({
  distributions: z.array(TagScoreDistributionSchema),
});

export type ScoreDistributionResponse = z.infer<typeof ScoreDistributionResponseSchema>;

// Run iteration request schema with Active Learning parameters
export const RunIterationRequestSchema = z.object({
  uncertainty_low: z.number().min(0).max(0.5).default(0.25),
  uncertainty_high: z.number().min(0.5).max(1).default(0.75),
  samples_per_iteration: z.number().int().min(5).max(100).default(20),
  selected_tag_ids: z.array(z.number().int()).nullable().optional(),
});

export type RunIterationRequest = z.infer<typeof RunIterationRequestSchema>;

// Export to annotation project request schema
export const ExportToAPRequestSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(2000).optional(),
  include_labeled: z.boolean().default(true),
  include_tag_ids: z.array(z.number().int()).nullable().optional(),
});

export type ExportToAPRequest = z.infer<typeof ExportToAPRequestSchema>;

// Export to annotation project response schema
export const ExportToAPResponseSchema = z.object({
  annotation_project_uuid: z.string().uuid(),
  annotation_project_name: z.string(),
  exported_count: z.number().int(),
  message: z.string(),
});

export type ExportToAPResponse = z.infer<typeof ExportToAPResponseSchema>;

// ML Project annotation project schema
export const MLProjectAnnotationProjectSchema = z.object({
  uuid: z.string().uuid(),
  name: z.string(),
  description: z.string(),
  source_search_session_uuid: z.string().uuid().nullable(),
  clip_count: z.number().int().default(0),
  created_on: z.coerce.date(),
});

export type MLProjectAnnotationProject = z.infer<typeof MLProjectAnnotationProjectSchema>;
