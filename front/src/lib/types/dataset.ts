import { z } from "zod";

import * as schemas from "@/lib/schemas";

export type Dataset = z.infer<typeof schemas.DatasetSchema>;

export type DatasetFilter = z.input<typeof schemas.DatasetFilterSchema>;

export type DatasetCreate = z.input<typeof schemas.DatasetCreateSchema>;

export type DatasetUpdate = z.input<typeof schemas.DatasetUpdateSchema>;

export type DatasetImport = z.infer<typeof schemas.DatasetImportSchema>;

export type DatasetCandidate = z.infer<typeof schemas.DatasetCandidateSchema>;

export type DatasetCandidateInfo = z.infer<
  typeof schemas.DatasetCandidateInfoSchema
>;

export type DatasetRecordingSite = z.infer<
  typeof schemas.DatasetRecordingSiteSchema
>;

export type DatasetRecordingCalendarBucket = z.infer<
  typeof schemas.DatasetRecordingCalendarBucketSchema
>;

export type DatasetRecordingHeatmapCell = z.infer<
  typeof schemas.DatasetRecordingHeatmapCellSchema
>;

export type DatasetRecordingTimelineSegment = z.infer<
  typeof schemas.DatasetRecordingTimelineSegmentSchema
>;

export type DatasetOverviewStats = z.infer<
  typeof schemas.DatasetOverviewStatsSchema
>;

export type DatasetDatetimePattern = z.infer<
  typeof schemas.DatasetDatetimePatternSchema
>;

export type DatasetDatetimePatternUpdate = z.input<
  typeof schemas.DatasetDatetimePatternUpdateSchema
>;

export type DatetimePatternType = z.infer<
  typeof schemas.DatasetDatetimePatternSchema
>["pattern_type"];
