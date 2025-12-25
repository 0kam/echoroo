"use client";

import { z } from "zod";

import { TagSchema } from "./tags";

// Custom model type enum
export const CustomModelTypeSchema = z.enum([
  "logistic_regression",
  "svm_linear",
  "mlp_small",
  "mlp_medium",
  "random_forest",
]);

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

// Main CustomModel schema
export const CustomModelSchema = z.object({
  uuid: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  ml_project_id: z.number().int(),
  target_tag_id: z.number().int(),
  target_tag: TagSchema,
  model_type: CustomModelTypeSchema,
  hyperparameters: z.record(z.unknown()).nullable(),
  status: CustomModelStatusSchema,
  training_session_ids: z.array(z.number().int()).nullable(),
  training_samples: z.number().int(),
  validation_samples: z.number().int(),
  accuracy: z.number().nullable(),
  precision: z.number().nullable(),
  recall: z.number().nullable(),
  f1_score: z.number().nullable(),
  confusion_matrix: z.record(z.unknown()).nullable(),
  training_started_on: z.coerce.date().nullable(),
  training_completed_on: z.coerce.date().nullable(),
  error_message: z.string().nullable(),
  created_by_id: z.string().uuid(),
  created_on: z.coerce.date(),
});

export type CustomModel = z.infer<typeof CustomModelSchema>;

// Create schema
export const CustomModelCreateSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional(),
  target_tag_id: z.number().int(),
  model_type: CustomModelTypeSchema,
  training_session_ids: z.array(z.string().uuid()).min(1, "At least one training session is required"),
  hyperparameters: z.record(z.unknown()).optional(),
});

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
