"use client";

import { z } from "zod";

import { TagSchema } from "./tags";

// Custom model type enum
export const CustomModelTypeSchema = z.enum(["svm"]);

export type CustomModelType = z.infer<typeof CustomModelTypeSchema>;

// Custom model status enum
export const CustomModelStatusSchema = z.enum([
  "draft",
  "training",
  "trained",
  "failed",
  "deployed",
  "archived",
]);

export type CustomModelStatus = z.infer<typeof CustomModelStatusSchema>;

// Custom model metrics schema
export const CustomModelMetricsSchema = z.object({
  accuracy: z.number().nullable(),
  precision: z.number().nullable(),
  recall: z.number().nullable(),
  f1_score: z.number().nullable(),
  roc_auc: z.number().nullable(),
  pr_auc: z.number().nullable(),
  confusion_matrix: z.array(z.array(z.number())).nullable(),
  training_samples: z.number().int(),
  validation_samples: z.number().int(),
  positive_samples: z.number().int(),
  negative_samples: z.number().int(),
});

export type CustomModelMetrics = z.infer<typeof CustomModelMetricsSchema>;

// Training config schema
export const CustomModelTrainingConfigSchema = z.object({
  model_type: CustomModelTypeSchema,
  train_split: z.number(),
  validation_split: z.number(),
  learning_rate: z.number(),
  batch_size: z.number().int(),
  max_epochs: z.number().int(),
  early_stopping_patience: z.number().int(),
  hidden_layers: z.array(z.number().int()),
  dropout_rate: z.number(),
  class_weight_balanced: z.boolean(),
  random_seed: z.number().int().nullable(),
});

export type CustomModelTrainingConfig = z.infer<typeof CustomModelTrainingConfigSchema>;

// Main CustomModel schema
export const CustomModelSchema = z.object({
  uuid: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  ml_project_uuid: z.string().uuid(),
  tag_id: z.number().int(),
  tag: TagSchema,
  model_type: CustomModelTypeSchema,
  status: CustomModelStatusSchema,
  training_config: CustomModelTrainingConfigSchema,
  metrics: CustomModelMetricsSchema.nullable(),
  model_path: z.string().nullable(),
  training_started_at: z.coerce.date().nullable(),
  training_completed_at: z.coerce.date().nullable(),
  training_duration_seconds: z.number().nullable(),
  error_message: z.string().nullable(),
  version: z.number().int(),
  is_active: z.boolean(),
  created_by_id: z.string().uuid(),
  created_on: z.coerce.date(),
  // Source information
  source_search_session_uuid: z.string().uuid().nullable().optional(),
  source_search_session_name: z.string().nullable().optional(),
  annotation_project_uuid: z.string().uuid().nullable().optional(),
  annotation_project_name: z.string().nullable().optional(),
});

export type CustomModel = z.infer<typeof CustomModelSchema>;

// Training data source type
export const TrainingDataSourceTypeSchema = z.enum([
  "search_session",
  "annotation_project",
]);

export type TrainingDataSourceType = z.infer<typeof TrainingDataSourceTypeSchema>;

// Create schema
export const CustomModelCreateSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional(),
  target_tag_id: z.number().int(),
  model_type: CustomModelTypeSchema,
  training_session_ids: z.array(z.string().uuid()).optional().default([]),
  annotation_project_uuids: z.array(z.string().uuid()).optional().default([]),
  hyperparameters: z.record(z.unknown()).optional(),
}).refine(
  (data) => (data.training_session_ids?.length ?? 0) > 0 || (data.annotation_project_uuids?.length ?? 0) > 0,
  { message: "At least one training session or annotation project is required" }
);

export type CustomModelCreate = z.infer<typeof CustomModelCreateSchema>;

// Training progress schema
export const TrainingProgressSchema = z.object({
  status: CustomModelStatusSchema,
  progress: z.number().min(0).max(100),
  current_epoch: z.number().int().optional(),
  total_epochs: z.number().int().optional(),
  current_accuracy: z.number().optional(),
  message: z.string().optional(),
});

export type TrainingProgress = z.infer<typeof TrainingProgressSchema>;
