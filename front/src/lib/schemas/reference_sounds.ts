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
  description: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
  ml_project_id: z.number().int().optional(),
  ml_project_uuid: z.string().uuid().optional(),
  source: ReferenceSoundSourceSchema,
  xeno_canto_id: z.string().nullable(),
  xeno_canto_url: z.string().nullable().optional(),
  audio_path: z.string().nullable().optional(),
  clip_id: z.number().int().nullable().optional(),
  clip: ClipSchema.nullable().optional(),
  tag_id: z.number().int().optional(),
  tag: TagSchema,
  start_time: z.number(),
  end_time: z.number(),
  has_embedding: z.boolean(),
  is_active: z.boolean(),
  created_by_id: z.string().uuid().optional(),
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
  clip_id: z.number().int().optional(),
  clip_uuid: z.string().uuid().optional(),
  tag_id: z.number().int(),
  name: z.string().min(1, "Name is required"),
  start_time: z.number().min(0).optional(),
  end_time: z.number().min(0).optional(),
}).refine(
  (data) => data.clip_id !== undefined || data.clip_uuid !== undefined,
  { message: "Either clip_id or clip_uuid is required" },
);

export type ReferenceSoundFromClip = z.infer<
  typeof ReferenceSoundFromClipSchema
>;

// Update reference sound
export const ReferenceSoundUpdateSchema = z.object({
  name: z.string().min(1).optional(),
  tag_id: z.number().int().optional(),
  start_time: z.number().min(0).optional(),
  end_time: z.number().min(0).optional(),
  notes: z.string().optional(),
  is_active: z.boolean().optional(),
});

export type ReferenceSoundUpdate = z.infer<typeof ReferenceSoundUpdateSchema>;
