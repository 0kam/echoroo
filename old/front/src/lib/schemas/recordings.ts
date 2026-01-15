import { z } from "zod";

import { TimeStringSchema } from "./common";
import { DatasetSchema } from "./datasets";
import { FeatureSchema } from "./features";
import { NoteAssociationSchema, NoteSchema } from "./notes";
import { TagAssociationSchema, TagSchema } from "./tags";
import { UserSchema } from "./users";

export const FileStateSchema = z.enum([
  "missing",
  "registered",
  "unregistered",
]);

export const DatetimeParseStatusSchema = z.enum([
  "pending",
  "success",
  "failed",
]);

export const RecordingSchema = z.object({
  uuid: z.string().uuid(),
  path: z.string(),
  hash: z.string(),
  duration: z.number(),
  channels: z.number().int(),
  samplerate: z.number().int(),
  time_expansion: z.number().default(1),

  // Primary datetime (from filename parsing)
  datetime: z.coerce.date().nullish(),
  datetime_parse_status: DatetimeParseStatusSchema,
  datetime_parse_error: z.string().nullish(),

  // Deprecated: Legacy fields (read-only, for backward compatibility)
  date: z.coerce.date().nullish(),
  time: TimeStringSchema.nullish(),

  // Primary location (H3 index from dataset site)
  h3_index: z.string().nullish(),

  // Deprecated: Legacy fields (read-only, for backward compatibility)
  latitude: z.number().nullish(),
  longitude: z.number().nullish(),

  // Audio metadata
  bit_depth: z.number().int().nullish(),

  rights: z.string().nullish(),
  tags: z.array(TagSchema).optional(),
  features: z.array(FeatureSchema).optional(),
  notes: z.array(NoteSchema).optional(),
  owners: z.array(UserSchema).optional(),
  dataset: DatasetSchema.nullish().optional(),
  created_on: z.coerce.date(),
});

export const RecordingUpdateSchema = z.object({
  // Note: datetime and h3_index are managed automatically
  // date/time/latitude/longitude are deprecated and no longer editable via UI
  rights: z.string().nullish(),
  time_expansion: z.coerce.number().optional(),
});

export const RecordingTagSchema = TagAssociationSchema.extend({
  recording_uuid: z.string().uuid(),
});

export const RecordingNoteSchema = NoteAssociationSchema.extend({
  recording_uuid: z.string().uuid(),
});

export const RecordingStateSchema = z.object({
  path: z.string(),
  state: FileStateSchema,
});
