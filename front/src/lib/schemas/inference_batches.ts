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

// Inference prediction review status enum
export const InferencePredictionReviewStatusSchema = z.enum([
  "unreviewed",
  "confirmed",
  "rejected",
  "uncertain",
]);

export type InferencePredictionReviewStatus = z.infer<
  typeof InferencePredictionReviewStatusSchema
>;

// Main InferenceBatch schema
export const InferenceBatchSchema = z.object({
  uuid: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  ml_project_id: z.number().int(),
  custom_model_id: z.number().int(),
  custom_model: CustomModelSchema,
  filter_config: z.record(z.unknown()).nullable(),
  confidence_threshold: z.number(),
  batch_size: z.number().int(),
  status: InferenceBatchStatusSchema,
  progress: z.number(),
  total_items: z.number().int(),
  processed_items: z.number().int(),
  positive_predictions: z.number().int(),
  started_on: z.coerce.date().nullable(),
  completed_on: z.coerce.date().nullable(),
  error_message: z.string().nullable(),
  created_by_id: z.string().uuid(),
  created_on: z.coerce.date(),
});

export type InferenceBatch = z.infer<typeof InferenceBatchSchema>;

// Create schema
export const InferenceBatchCreateSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional(),
  custom_model_id: z.string().uuid(),
  filter_config: z.record(z.unknown()).optional(),
  confidence_threshold: z.number().min(0).max(1).optional(),
  batch_size: z.number().int().min(1).optional(),
});

export type InferenceBatchCreate = z.infer<typeof InferenceBatchCreateSchema>;

// InferencePrediction schema
export const InferencePredictionSchema = z.object({
  uuid: z.string().uuid(),
  inference_batch_id: z.number().int(),
  clip_id: z.number().int(),
  clip: ClipSchema,
  confidence: z.number(),
  predicted_positive: z.boolean(),
  review_status: InferencePredictionReviewStatusSchema,
  reviewed_by_id: z.string().uuid().nullable(),
  reviewed_on: z.coerce.date().nullable(),
  notes: z.string().nullable(),
});

export type InferencePrediction = z.infer<typeof InferencePredictionSchema>;

// Prediction review schema
export const InferencePredictionReviewSchema = z.object({
  review_status: InferencePredictionReviewStatusSchema,
  notes: z.string().optional(),
});

export type InferencePredictionReview = z.infer<
  typeof InferencePredictionReviewSchema
>;

// Inference progress schema
export const InferenceProgressSchema = z.object({
  status: InferenceBatchStatusSchema,
  progress: z.number().min(0).max(100),
  processed_items: z.number().int(),
  total_items: z.number().int(),
  positive_predictions: z.number().int(),
});

export type InferenceProgress = z.infer<typeof InferenceProgressSchema>;
