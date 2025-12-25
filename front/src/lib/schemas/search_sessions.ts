"use client";

import { z } from "zod";

import { ClipSchema } from "./clips";
import { ReferenceSoundSchema } from "./reference_sounds";
import { TagSchema } from "./tags";

// Search result label enum
export const SearchResultLabelSchema = z.enum([
  "unlabeled",
  "positive",
  "negative",
  "uncertain",
  "skipped",
]);

export type SearchResultLabel = z.infer<typeof SearchResultLabelSchema>;

// Main SearchSession schema
export const SearchSessionSchema = z.object({
  uuid: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  ml_project_id: z.number().int(),
  target_tag_id: z.number().int(),
  target_tag: TagSchema,
  similarity_threshold: z.number(),
  max_results: z.number().int(),
  filter_config: z.record(z.unknown()).nullable(),
  is_search_complete: z.boolean(),
  is_labeling_complete: z.boolean(),
  reference_sounds: z.array(ReferenceSoundSchema).default([]),
  result_count: z.number().int(),
  labeled_count: z.number().int(),
  created_by_id: z.string().uuid(),
  created_on: z.coerce.date(),
});

export type SearchSession = z.infer<typeof SearchSessionSchema>;

// Create schema
export const SearchSessionCreateSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional(),
  target_tag_id: z.number().int(),
  reference_sound_ids: z.array(z.string().uuid()).min(1, "At least one reference sound is required"),
  similarity_threshold: z.number().min(0).max(1).optional(),
  max_results: z.number().int().min(1).optional(),
  filter_config: z.record(z.unknown()).optional(),
});

export type SearchSessionCreate = z.infer<typeof SearchSessionCreateSchema>;

// SearchResult schema
export const SearchResultSchema = z.object({
  uuid: z.string().uuid(),
  search_session_id: z.number().int(),
  clip_id: z.number().int(),
  clip: ClipSchema,
  similarity: z.number(),
  rank: z.number().int(),
  label: SearchResultLabelSchema,
  labeled_by_id: z.string().uuid().nullable(),
  labeled_on: z.coerce.date().nullable(),
  notes: z.string().nullable(),
});

export type SearchResult = z.infer<typeof SearchResultSchema>;

// Label update schema
export const SearchResultLabelUpdateSchema = z.object({
  label: SearchResultLabelSchema,
  notes: z.string().optional(),
});

export type SearchResultLabelUpdate = z.infer<
  typeof SearchResultLabelUpdateSchema
>;

// Bulk label request schema
export const BulkLabelRequestSchema = z.object({
  result_uuids: z.array(z.string().uuid()).min(1),
  label: SearchResultLabelSchema,
});

export type BulkLabelRequest = z.infer<typeof BulkLabelRequestSchema>;

// Search progress schema
export const SearchProgressSchema = z.object({
  total: z.number().int(),
  labeled: z.number().int(),
  positive: z.number().int(),
  negative: z.number().int(),
  uncertain: z.number().int(),
  skipped: z.number().int(),
  unlabeled: z.number().int(),
});

export type SearchProgress = z.infer<typeof SearchProgressSchema>;
