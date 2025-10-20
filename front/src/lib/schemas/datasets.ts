"use client";

import { z } from "zod";

import { FileSchema } from "./common";

export const VisibilityLevelSchema = z.enum([
  "public",
  "restricted",
  "private",
]);
export type VisibilityLevel = z.infer<typeof VisibilityLevelSchema>;

export const DatasetSchema = z.object({
  uuid: z.string().uuid(),
  name: z.string(),
  audio_dir: z.string(),
  description: z.string(),
  recording_count: z.number().int().default(0),
  created_on: z.coerce.date(),
  visibility: VisibilityLevelSchema,
  created_by_id: z.string().uuid(),
  owner_group_id: z.number().int().positive().nullable(),
});

export const DatasetCreateSchema = z
  .object({
    uuid: z.string().uuid().optional(),
    name: z.string().min(1),
    audio_dir: z.string().min(1, "Select an audio directory"),
    description: z.string().optional(),
    visibility: VisibilityLevelSchema.default("private"),
    owner_group_id: z.number().int().positive().nullable().optional(),
  })
  .superRefine((data, ctx) => {
    if (data.visibility === "restricted" && data.owner_group_id == null) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Restricted visibility requires selecting a group",
        path: ["owner_group_id"],
      });
    }

    if (
      data.visibility !== "restricted" &&
      data.owner_group_id != null
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Only restricted visibility can have a group",
        path: ["owner_group_id"],
      });
    }
  });

export const DatasetUpdateSchema = z
  .object({
    name: z.string().min(1).optional(),
    description: z.string().optional(),
    visibility: VisibilityLevelSchema.optional(),
    owner_group_id: z.number().int().positive().nullable().optional(),
  })
  .superRefine((data, ctx) => {
    if (
      data.visibility === "restricted" &&
      data.owner_group_id == null
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Restricted visibility requires selecting a group",
        path: ["owner_group_id"],
      });
    }

    if (
      data.visibility != null &&
      data.visibility !== "restricted" &&
      data.owner_group_id != null
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Only restricted visibility can have a group",
        path: ["owner_group_id"],
      });
    }
  });

export const DatasetImportSchema = z.object({
  dataset: FileSchema,
  audio_dir: z.string(),
});

export const DatasetCandidateSchema = z.object({
  name: z.string(),
  relative_path: z.string(),
  absolute_path: z.string(),
});

export const DatasetCandidateInfoSchema = z.object({
  relative_path: z.string(),
  absolute_path: z.string(),
  has_nested_directories: z.boolean(),
  audio_file_count: z.number().int(),
});
