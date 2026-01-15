"use client";

import { z } from "zod";

import { ClipSchema } from "./clips";
import { CustomModelSchema } from "./custom_models";

// Inference batch status enum
export const InferenceBatchStatusSchema = z.enum([
  "pending",
  "running",
  "completed",
  "failed",
  "cancelled",
]);

export type InferenceBatchStatus = z.infer<typeof InferenceBatchStatusSchema>;

// Main InferenceBatch schema
export const InferenceBatchSchema = z.object({
  uuid: z.string().uuid(),
  name: z.string().nullable(),
  ml_project_uuid: z.string().uuid(),
  custom_model: CustomModelSchema.nullable(),
  status: InferenceBatchStatusSchema,
  confidence_threshold: z.number(),
  total_clips: z.number().int(),
  processed_clips: z.number().int(),
  total_predictions: z.number().int(),
  positive_predictions_count: z.number().int(),
  negative_predictions_count: z.number().int(),
  average_confidence: z.number().nullable(),
  started_at: z.coerce.date().nullable(),
  completed_at: z.coerce.date().nullable(),
  duration_seconds: z.number().nullable(),
  error_message: z.string().nullable(),
  description: z.string().nullable(),
  created_by_id: z.string().uuid(),
  created_on: z.coerce.date(),
});

export type InferenceBatch = z.infer<typeof InferenceBatchSchema>;

// Create schema
export const InferenceBatchCreateSchema = z.object({
  name: z.string().optional(),
  custom_model_id: z.number().int().optional(),
  custom_model_uuid: z.string().uuid().optional(),
  confidence_threshold: z.number().min(0).max(1).optional(),
  clip_ids: z.array(z.number().int()).optional(),
  include_all_clips: z.boolean().optional(),
  exclude_already_labeled: z.boolean().optional(),
  description: z.string().optional(),
});

export type InferenceBatchCreate = z.infer<typeof InferenceBatchCreateSchema>;

// InferencePrediction schema
export const InferencePredictionSchema = z.object({
  uuid: z.string().uuid(),
  inference_batch_uuid: z.string().uuid(),
  clip: ClipSchema,
  confidence: z.number(),
  predicted_positive: z.boolean(),
  created_on: z.coerce.date(),
});

export type InferencePrediction = z.infer<typeof InferencePredictionSchema>;

// Inference progress schema
export const InferenceProgressSchema = z.object({
  status: InferenceBatchStatusSchema,
  progress: z.number().min(0).max(100),
  processed_items: z.number().int(),
  total_items: z.number().int(),
  positive_predictions: z.number().int(),
});

export type InferenceProgress = z.infer<typeof InferenceProgressSchema>;

// Convert to annotation project request schema
export const ConvertToAnnotationProjectRequestSchema = z.object({
  name: z.string().min(1).max(255),
  description: z.string().optional(),
  confidence_threshold: z.number().min(0).max(1).optional(),
  include_only_positive: z.boolean().optional().default(true),
});

export type ConvertToAnnotationProjectRequest = z.infer<
  typeof ConvertToAnnotationProjectRequestSchema
>;

// Note: ConvertToAnnotationProjectResponse is not needed as the API returns AnnotationProject
