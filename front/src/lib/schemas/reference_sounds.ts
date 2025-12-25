"use client";

import { z } from "zod";

import { ClipSchema } from "./clips";
import { TagSchema } from "./tags";

// Reference sound source enum
export const ReferenceSoundSourceSchema = z.enum([
  "xeno_canto",
  "custom_upload",
  "dataset_clip",
]);

export type ReferenceSoundSource = z.infer<typeof ReferenceSoundSourceSchema>;

// Main ReferenceSound schema
export const ReferenceSoundSchema = z.object({
  uuid: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  ml_project_id: z.number().int(),
  source: ReferenceSoundSourceSchema,
  xeno_canto_id: z.string().nullable(),
  xeno_canto_url: z.string().nullable(),
  audio_path: z.string().nullable(),
  clip_id: z.number().int().nullable(),
  clip: ClipSchema.nullable(),
  tag_id: z.number().int(),
  tag: TagSchema,
  start_time: z.number(),
  end_time: z.number(),
  has_embedding: z.boolean(),
  is_active: z.boolean(),
  created_by_id: z.string().uuid(),
  created_on: z.coerce.date(),
});

export type ReferenceSound = z.infer<typeof ReferenceSoundSchema>;

// Create from Xeno-Canto
export const ReferenceSoundFromXenoCantoSchema = z.object({
  xeno_canto_id: z.string().min(1, "Xeno-Canto ID is required"),
  tag_id: z.number().int(),
  name: z.string().min(1, "Name is required"),
  start_time: z.number().min(0).optional(),
  end_time: z.number().min(0).optional(),
});

export type ReferenceSoundFromXenoCanto = z.infer<
  typeof ReferenceSoundFromXenoCantoSchema
>;

// Create from dataset clip
export const ReferenceSoundFromClipSchema = z.object({
  clip_id: z.number().int(),
  tag_id: z.number().int(),
  name: z.string().min(1, "Name is required"),
  start_time: z.number().min(0).optional(),
  end_time: z.number().min(0).optional(),
});

export type ReferenceSoundFromClip = z.infer<
  typeof ReferenceSoundFromClipSchema
>;
