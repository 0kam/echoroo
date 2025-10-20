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
  owner_group_id: z.number().int().positive().nullable(),
});

export const AnnotationProjectCreateSchema = z
  .object({
    name: z.string().min(1),
    description: z.string().min(1),
    annotation_instructions: z.string().nullable().optional(),
    visibility: VisibilityLevelSchema.default("private"),
    owner_group_id: z.number().int().positive().nullable().optional(),
  })
  .superRefine((data, ctx) => {
    if (data.visibility === "restricted" && data.owner_group_id == null) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["owner_group_id"],
        message: "Restricted visibility requires selecting a group",
      });
    }

    if (
      data.visibility !== "restricted" &&
      data.owner_group_id != null
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["owner_group_id"],
        message: "Only restricted visibility can have a group",
      });
    }
  });

export const AnnotationProjectUpdateSchema = z
  .object({
    name: z.string().optional(),
    description: z.string().optional(),
    annotation_instructions: z.string().optional(),
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
        path: ["owner_group_id"],
        message: "Changing to restricted visibility requires a group",
      });
    }

    if (
      data.visibility != null &&
      data.visibility !== "restricted" &&
      data.owner_group_id != null
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["owner_group_id"],
        message: "Only restricted visibility can have a group",
      });
    }
  });

export const AnnotationProjectImportSchema = z.object({
  annotation_project: FileSchema,
});
