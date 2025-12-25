import { z } from "zod";

import * as schemas from "@/lib/schemas";

export type FoundationModel = z.infer<typeof schemas.FoundationModelSchema>;

export type FoundationModelRunStatus = z.infer<
  typeof schemas.FoundationModelRunStatusSchema
>;

export type FoundationModelRun = z.infer<
  typeof schemas.FoundationModelRunSchema
>;

export type FoundationModelRunSpecies = z.infer<
  typeof schemas.FoundationModelRunSpeciesSchema
>;

export type DatasetFoundationModelSummary = z.infer<
  typeof schemas.DatasetFoundationModelSummarySchema
>;

export type FoundationModelRunCreate = z.input<
  typeof schemas.FoundationModelRunCreateSchema
>;

// ============================================================================
// Foundation Model Run Progress
// ============================================================================

export type FoundationModelRunProgress = z.infer<
  typeof schemas.FoundationModelRunProgressSchema
>;

// ============================================================================
// Detection Types
// ============================================================================

export type FoundationModelDetectionReviewStatus = z.infer<
  typeof schemas.FoundationModelDetectionReviewStatusSchema
>;

export type FoundationModelDetection = z.infer<
  typeof schemas.FoundationModelDetectionSchema
>;

export type FoundationModelDetectionReview = z.infer<
  typeof schemas.FoundationModelDetectionReviewSchema
>;

export type FoundationModelDetectionReviewUpdate = z.input<
  typeof schemas.FoundationModelDetectionReviewUpdateSchema
>;

// ============================================================================
// Summary Types
// ============================================================================

export type FoundationModelSpeciesSummary = z.infer<
  typeof schemas.FoundationModelSpeciesSummarySchema
>;

export type FoundationModelDetectionSummary = z.infer<
  typeof schemas.FoundationModelDetectionSummarySchema
>;

export type BulkReviewResponse = z.infer<
  typeof schemas.BulkReviewResponseSchema
>;
