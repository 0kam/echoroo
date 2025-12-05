import { z } from "zod";

import { ClipSchema } from "./clips";
import { DatasetSchema } from "./datasets";
import { ModelRunSchema } from "./model_runs";
import { RecordingSchema } from "./recordings";

// Model name enum
export const InferenceModelNameSchema = z.enum(["birdnet", "perch"]);

// Inference job status enum
export const InferenceJobStatusSchema = z.enum([
  "pending",
  "running",
  "completed",
  "failed",
  "cancelled",
]);

// Inference configuration schema
export const InferenceConfigSchema = z.object({
  model_name: InferenceModelNameSchema,
  model_version: z.string(),
  confidence_threshold: z.number().min(0).max(1),
  overlap: z.number().min(0).max(1),
  batch_size: z.number().int().positive(),
  use_gpu: z.boolean(),
  use_metadata_filter: z.boolean(),
  custom_species_list: z.array(z.string()).nullable(),
  store_embeddings: z.boolean(),
  store_predictions: z.boolean(),
});

// Inference job schema
export const InferenceJobSchema = z.object({
  uuid: z.string().uuid(),
  status: InferenceJobStatusSchema,
  progress: z.number().min(0).max(100),
  total_items: z.number().int().nonnegative(),
  processed_items: z.number().int().nonnegative(),
  error_message: z.string().nullable(),
  config: InferenceConfigSchema,
  started_on: z.coerce.date().nullable(),
  completed_on: z.coerce.date().nullable(),
  model_run: ModelRunSchema.nullable(),
  dataset: DatasetSchema.nullable(),
  recording: RecordingSchema.nullable(),
});

// Search result item schema
export const SearchResultItemSchema = z.object({
  clip: ClipSchema,
  recording: RecordingSchema,
  similarity: z.number(),
  model_run: ModelRunSchema,
});

// Create inference job request schemas
export const CreateDatasetInferenceJobSchema = z.object({
  dataset_uuid: z.string().uuid(),
  config: InferenceConfigSchema,
});

export const CreateRecordingInferenceJobSchema = z.object({
  recording_uuid: z.string().uuid(),
  config: InferenceConfigSchema,
});

// Search similar clips request schema
export const SearchSimilarClipsRequestSchema = z.object({
  clip_uuid: z.string().uuid(),
  model_run_uuid: z.string().uuid(),
  dataset_uuid: z.string().uuid().optional(),
  limit: z.number().int().positive().optional(),
  offset: z.number().int().nonnegative().optional(),
  min_similarity: z.number().min(0).max(1).optional(),
});

// Search similar clips response schema
export const SearchSimilarClipsResponseSchema = z.object({
  results: z.array(SearchResultItemSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
});

// Get random clips request schema
export const GetRandomClipsRequestSchema = z.object({
  model_run_uuid: z.string().uuid(),
  dataset_uuid: z.string().uuid().optional(),
  count: z.number().int().positive().optional(),
});

// Get random clips response schema
export const GetRandomClipsResponseSchema = z.object({
  clips: z.array(SearchResultItemSchema),
  total_available: z.number().int().nonnegative(),
});

// Inference job filter schema
export const InferenceJobFilterSchema = z.object({
  status: InferenceJobStatusSchema.optional(),
  model_name: InferenceModelNameSchema.optional(),
  dataset_uuid: z.string().uuid().optional(),
  recording_uuid: z.string().uuid().optional(),
});
