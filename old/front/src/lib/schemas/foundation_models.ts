"use client";

import { z } from "zod";

import { ClipSchema } from "./clips";
import { DatasetSchema } from "./datasets";
import { TagSchema } from "./tags";
import { SimpleUserSchema } from "./users";

export const FoundationModelSchema = z.object({
  uuid: z.string().uuid(),
  slug: z.string(),
  display_name: z.string(),
  provider: z.string(),
  version: z.string(),
  description: z.string().nullable().optional(),
  default_confidence_threshold: z.number(),
  is_active: z.boolean(),
  created_on: z.coerce.date(),
});

export const FoundationModelRunStatusSchema = z.enum([
  "queued",
  "running",
  "post_processing",
  "completed",
  "failed",
  "cancelled",
]);

export const FoundationModelRunSpeciesSchema = z.object({
  gbif_taxon_id: z.string().nullable().optional(),
  annotation_tag_id: z.number().nullable().optional(),
  tag: TagSchema.nullish(),
  scientific_name: z.string(),
  vernacular_name: z.string().nullable().optional(),
  detection_count: z.number(),
  avg_confidence: z.number(),
  created_on: z.coerce.date(),
});

export const FoundationModelRunSchema = z.object({
  uuid: z.string().uuid(),
  foundation_model_id: z.number().optional(),
  dataset_id: z.number().optional(),
  requested_by_id: z.string().uuid().nullable().optional(),
  foundation_model: FoundationModelSchema.nullish(),
  dataset: DatasetSchema.nullish(),
  requested_by: SimpleUserSchema.nullish(),
  status: FoundationModelRunStatusSchema,
  confidence_threshold: z.number(),
  scope: z.record(z.any()).nullable().optional(),
  progress: z.number().optional(),
  total_recordings: z.number().optional(),
  processed_recordings: z.number().optional(),
  total_clips: z.number().optional(),
  total_detections: z.number().optional(),
  classification_csv_path: z.string().nullable().optional(),
  embedding_store_key: z.string().nullable().optional(),
  summary: z.record(z.any()).nullable().optional(),
  error: z.record(z.any()).nullable().optional(),
  started_on: z.coerce.date().nullable().optional(),
  completed_on: z.coerce.date().nullable().optional(),
  created_on: z.coerce.date(),
  species: z.array(FoundationModelRunSpeciesSchema).nullable().optional(),
});

export const DatasetFoundationModelSummarySchema = z.object({
  foundation_model: FoundationModelSchema,
  latest_run: FoundationModelRunSchema.nullish(),
  last_completed_run: FoundationModelRunSchema.nullish(),
});

export const FoundationModelRunCreateSchema = z.object({
  dataset_uuid: z.string().uuid(),
  foundation_model_slug: z.string(),
  confidence_threshold: z.number().min(0).max(1).optional(),
  scope: z.record(z.any()).optional(),
  locale: z.string().optional(),
  run_embeddings: z.boolean().optional().default(true),
  run_predictions: z.boolean().optional().default(true),
});

// ============================================================================
// Foundation Model Run Progress
// ============================================================================

export const FoundationModelRunProgressSchema = z.object({
  status: FoundationModelRunStatusSchema,
  progress: z.number(),
  total_recordings: z.number().int(),
  processed_recordings: z.number().int(),
  total_clips: z.number().int(),
  total_detections: z.number().int(),
  recordings_per_second: z.number().nullable(),
  estimated_time_remaining_seconds: z.number().nullable(),
  message: z.string().nullable(),
});

// ============================================================================
// Foundation Model Detection Review Status
// ============================================================================

export const FoundationModelDetectionReviewStatusSchema = z.enum([
  "unreviewed",
  "confirmed",
  "rejected",
  "uncertain",
]);

// ============================================================================
// Foundation Model Detection Result
// ============================================================================

export const FoundationModelDetectionSchema = z.object({
  uuid: z.string().uuid(),
  clip_id: z.number().int(),
  clip: z.lazy(() => ClipSchema),
  species_tag: TagSchema,
  confidence: z.number(),
  review_status: FoundationModelDetectionReviewStatusSchema,
  reviewed_on: z.coerce.date().nullable(),
  reviewed_by_id: z.string().uuid().nullable(),
  notes: z.string().nullable(),
  converted_to_annotation: z.boolean(),
  is_included: z.boolean().nullable(),
  occurrence_probability: z.number().nullable(),
});

// ============================================================================
// Foundation Model Detection Review
// ============================================================================

export const FoundationModelDetectionReviewSchema = z.object({
  uuid: z.string().uuid(),
  // Note: clip_prediction_id and species_detection_job_id are excluded in backend response
  status: FoundationModelDetectionReviewStatusSchema,
  reviewed_by_id: z.string().uuid().nullable(),
  reviewed_on: z.coerce.date().nullable(),
  notes: z.string().nullable(),
  converted_to_annotation: z.boolean(),
  clip_annotation_id: z.number().int().nullable(),
});

export const FoundationModelDetectionReviewUpdateSchema = z.object({
  status: FoundationModelDetectionReviewStatusSchema,
  notes: z.string().optional(),
});

// ============================================================================
// Species Summary
// ============================================================================

export const FoundationModelSpeciesSummarySchema = z.object({
  tag_id: z.number().int(),
  tag_value: z.string(),
  total_detections: z.number().int(),
  confirmed_count: z.number().int(),
  rejected_count: z.number().int(),
  uncertain_count: z.number().int(),
  unreviewed_count: z.number().int(),
  average_confidence: z.number().nullable(),
});

// ============================================================================
// Detection Summary
// ============================================================================

export const FoundationModelDetectionSummarySchema = z.object({
  total_detections: z.number().int(),
  unique_species: z.number().int(),
  species_summary: z.array(FoundationModelSpeciesSummarySchema),
  total_reviewed: z.number().int(),
  total_confirmed: z.number().int(),
  total_rejected: z.number().int(),
  total_uncertain: z.number().int(),
  total_unreviewed: z.number().int(),
  // Optional fields (not currently computed by backend)
  confidence_histogram: z.array(z.number().int()).optional(),
  detections_by_date: z.record(z.number().int()).optional(),
  detections_by_location: z.record(z.number().int()).optional(),
});

// ============================================================================
// Bulk Review Response
// ============================================================================

export const BulkReviewResponseSchema = z.object({
  reviewed_count: z.number().int(),
});

// ============================================================================
// Job Queue Status
// ============================================================================

export const JobQueueStatusSchema = z.object({
  pending: z.number().int(),
  running: z.number().int(),
  completed: z.number().int(),
  failed: z.number().int(),
});

// ============================================================================
// Convert to Annotation Project Response
// ============================================================================

export const ConvertToAnnotationProjectResponseSchema = z.object({
  annotation_project_uuid: z.string().uuid(),
  annotation_project_name: z.string(),
  total_tasks_created: z.number().int(),
  total_annotations_created: z.number().int(),
});
