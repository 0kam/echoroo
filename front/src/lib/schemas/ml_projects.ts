"use client";

import { z } from "zod";

import { DatasetSchema } from "./datasets";
import { FoundationModelRunSchema } from "./foundation_models";
import { ModelRunSchema } from "./model_runs";
import { TagSchema } from "./tags";

// MLProject status enum - matches backend MLProjectStatus
export const MLProjectStatusSchema = z.enum([
  "draft",
  "active",
  "training",
  "inference",
  "completed",
  "archived",
]);

export type MLProjectStatus = z.infer<typeof MLProjectStatusSchema>;

// Main MLProject schema - matches backend MLProject schema
export const MLProjectSchema = z.object({
  uuid: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  dataset_id: z.number().int().nullable().optional(),
  dataset: DatasetSchema.nullable().optional(),
  embedding_model_run_id: z.number().int().nullable().optional(),
  embedding_model_run: ModelRunSchema.nullable().optional(),
  foundation_model_id: z.number().int().nullable().optional(),
  status: MLProjectStatusSchema,
  default_similarity_threshold: z.number(),
  target_tags: z.array(TagSchema).default([]),
  created_by_id: z.string().uuid(),
  created_on: z.coerce.date(),
  project_id: z.string().optional(),
  // Stats
  dataset_scope_count: z.number().int().default(0),
  reference_sound_count: z.number().int().default(0),
  search_session_count: z.number().int().default(0),
  custom_model_count: z.number().int().default(0),
  inference_batch_count: z.number().int().default(0),
});

export type MLProject = z.infer<typeof MLProjectSchema>;

// Create schema - simplified, datasets are added in the Datasets tab
export const MLProjectCreateSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional(),
});

export type MLProjectCreate = z.infer<typeof MLProjectCreateSchema>;

// Update schema
export const MLProjectUpdateSchema = z.object({
  name: z.string().min(1).optional(),
  description: z.string().nullable().optional(),
  status: MLProjectStatusSchema.optional(),
  embedding_model_run_id: z.number().int().nullable().optional(),
  default_similarity_threshold: z.number().min(0).max(1).optional(),
});

export type MLProjectUpdate = z.infer<typeof MLProjectUpdateSchema>;

// Filter schema
export const MLProjectFilterSchema = z.object({
  dataset_id: z.number().int().positive().optional(),
  status: MLProjectStatusSchema.optional(),
});

// ============================================================================
// MLProject Dataset Scope
// ============================================================================

export const MLProjectDatasetScopeCreateSchema = z.object({
  dataset_uuid: z.string().uuid(),
  foundation_model_run_uuid: z.string().uuid(),
});

export const MLProjectDatasetScopeSchema = z.object({
  uuid: z.string().uuid(),
  dataset: DatasetSchema,
  foundation_model_run: FoundationModelRunSchema,
  created_on: z.coerce.date(),
});
