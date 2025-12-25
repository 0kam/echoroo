"use client";

import { z } from "zod";

import { DatasetSchema } from "./datasets";
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
  dataset_id: z.number().int(),
  dataset: DatasetSchema.nullable().optional(),
  embedding_model_run_id: z.number().int().nullable(),
  embedding_model_run: ModelRunSchema.nullable().optional(),
  status: MLProjectStatusSchema,
  default_similarity_threshold: z.number(),
  target_tags: z.array(TagSchema).default([]),
  created_by_id: z.string().uuid(),
  created_on: z.coerce.date(),
  // Stats
  reference_sound_count: z.number().int().default(0),
  search_session_count: z.number().int().default(0),
  custom_model_count: z.number().int().default(0),
  inference_batch_count: z.number().int().default(0),
});

export type MLProject = z.infer<typeof MLProjectSchema>;

// Create schema
export const MLProjectCreateSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().min(1, "Description is required"),
  dataset_uuid: z.string().uuid(),
  embedding_model_run_id: z.number().int().optional(),
  default_similarity_threshold: z.number().min(0).max(1).optional(),
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
