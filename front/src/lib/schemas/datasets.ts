"use client";

import { z } from "zod";

import {
  LicenseSchema,
  ProjectSchema,
  RecorderSchema,
  SiteSchema,
} from "./metadata";
import { FileSchema } from "./common";

export const VisibilityLevelSchema = z.enum(["public", "restricted"]);
export type VisibilityLevel = z.infer<typeof VisibilityLevelSchema>;

const optionalTrimmedString = z
  .string()
  .optional()
  .transform((value) => {
    if (value === undefined) {
      return undefined;
    }
    const trimmed = value.trim();
    return trimmed === "" ? undefined : trimmed;
  });

const optionalNullableTrimmedString = z
  .string()
  .nullable()
  .optional()
  .transform((value) => {
    if (value === undefined) {
      return undefined;
    }
    if (value === null) {
      return null;
    }
    const trimmed = value.trim();
    return trimmed === "" ? null : trimmed;
  });

export const DatasetSchema = z.object({
  uuid: z.string().uuid(),
  id: z.number().int().optional(),
  name: z.string(),
  audio_dir: z.string(),
  description: z.string().nullable().optional(),
  recording_count: z.number().int().default(0),
  recording_start_date: z.coerce.date().nullable().optional(),
  recording_end_date: z.coerce.date().nullable().optional(),
  created_on: z.coerce.date(),
  visibility: VisibilityLevelSchema,
  created_by_id: z.string().uuid(),
  project_id: z.string(),
  primary_site_id: z.string().nullable().optional(),
  primary_recorder_id: z.string().nullable().optional(),
  license_id: z.string().nullable().optional(),
  doi: z.string().nullable().optional(),
  note: z.string().nullable().optional(),
  gain: z.number().nullable().optional(),
  project: ProjectSchema.nullable().optional(),
  primary_site: SiteSchema.nullable().optional(),
  primary_recorder: RecorderSchema.nullable().optional(),
  license: LicenseSchema.nullable().optional(),
});

export const DatasetCreateSchema = z.object({
  uuid: z.string().uuid().optional(),
  name: z.string().min(1),
  audio_dir: z.string().min(1, "Select an audio directory"),
  description: optionalTrimmedString,
  visibility: VisibilityLevelSchema.default("restricted"),
  project_id: z.string().min(1, "Select a project"),
  primary_site_id: optionalNullableTrimmedString,
  primary_recorder_id: optionalNullableTrimmedString,
  license_id: optionalNullableTrimmedString,
  doi: optionalTrimmedString,
  note: optionalTrimmedString,
  gain: z.number().nullable().optional(),
});

export const DatasetUpdateSchema = z.object({
  name: z.string().min(1).optional(),
  description: optionalTrimmedString,
  visibility: VisibilityLevelSchema.optional(),
  project_id: optionalNullableTrimmedString,
  primary_site_id: optionalNullableTrimmedString,
  primary_recorder_id: optionalNullableTrimmedString,
  license_id: optionalNullableTrimmedString,
  doi: optionalNullableTrimmedString,
  note: optionalTrimmedString,
  gain: z.number().nullable().optional(),
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

export const DatasetRecordingSiteSchema = z.object({
  h3_index: z.string().nullable().optional(),
  latitude: z.number(),
  longitude: z.number(),
  recording_count: z.number().int(),
  label: z.string().nullable().optional(),
});

export const DatasetRecordingCalendarBucketSchema = z.object({
  date: z.coerce.date(),
  count: z.number().int(),
});

export const DatasetRecordingHeatmapCellSchema = z.object({
  date: z.coerce.date(),
  hour: z.number().int(),
  count: z.number().int(),
  duration_minutes: z.number(),
});

export const DatasetRecordingTimelineSegmentSchema = z.object({
  recording_uuid: z.string().uuid(),
  start: z.coerce.date(),
  end: z.coerce.date(),
  path: z.string(),
});

export const DatasetOverviewStatsSchema = z.object({
  recording_sites: z.array(DatasetRecordingSiteSchema),
  recording_calendar: z.array(DatasetRecordingCalendarBucketSchema),
  recording_heatmap: z.array(DatasetRecordingHeatmapCellSchema),
  recording_timeline: z.array(DatasetRecordingTimelineSegmentSchema),
  total_duration_seconds: z.number().nullable().optional(),
});

export const DatasetDatetimePatternSchema = z.object({
  dataset_id: z.number().int(),
  pattern_type: z.enum(["strptime", "regex"]),
  pattern: z.string().min(1),
  sample_filename: z.string().nullable().optional(),
  sample_result: z.coerce.date().nullable().optional(),
  uuid: z.string().uuid().optional(),
  created_on: z.coerce.date().optional(),
});

export const DatasetDatetimePatternUpdateSchema = z.object({
  pattern_type: z.enum(["strptime", "regex"]),
  pattern: z.string().min(1),
  sample_filename: z.string().optional(),
});
