"use client";

import { z } from "zod";

import { FileSchema } from "./common";
import { VisibilityLevelSchema } from "./datasets";
import { TagSchema } from "./tags";

export const AnnotationProjectSchema = z.object({
  uuid: z.string().uuid(),
  name: z.string(),
  description: z.string(),
  annotation_instructions: z.string().nullish(),
  tags: z.array(TagSchema).optional().default([]),
  created_on: z.coerce.date(),
  visibility: VisibilityLevelSchema,
  created_by_id: z.string().uuid(),
  dataset_id: z.number().int(),
  project_id: z.string(),
});

export const AnnotationProjectCreateSchema = z.object({
  name: z.string().min(1),
  description: z.string().min(1),
  annotation_instructions: z.string().nullable().optional(),
  visibility: VisibilityLevelSchema.default("restricted"),
  dataset_id: z.number().int(),
});

export const AnnotationProjectUpdateSchema = z.object({
  name: z.string().optional(),
  description: z.string().optional(),
  annotation_instructions: z.string().optional(),
  visibility: VisibilityLevelSchema.optional(),
  dataset_id: z.number().int().optional(),
});

export const AnnotationProjectImportSchema = z.object({
  annotation_project: FileSchema,
});
