import { z } from "zod";

import * as schemas from "@/lib/schemas";

// ============================================================================
// MLProject Types
// ============================================================================

export type MLProjectStatus = z.infer<typeof schemas.MLProjectStatusSchema>;

export type MLProject = z.infer<typeof schemas.MLProjectSchema>;

export type MLProjectCreate = z.input<typeof schemas.MLProjectCreateSchema>;

export type MLProjectUpdate = z.input<typeof schemas.MLProjectUpdateSchema>;

// ============================================================================
// ReferenceSound Types
// ============================================================================

export type ReferenceSoundSource = z.infer<
  typeof schemas.ReferenceSoundSourceSchema
>;

export type ReferenceSound = z.infer<typeof schemas.ReferenceSoundSchema>;

export type ReferenceSoundFromXenoCanto = z.input<
  typeof schemas.ReferenceSoundFromXenoCantoSchema
>;

export type ReferenceSoundFromClip = z.input<
  typeof schemas.ReferenceSoundFromClipSchema
>;

export type ReferenceSoundUpdate = z.input<
  typeof schemas.ReferenceSoundUpdateSchema
>;

// ============================================================================
// SearchSession Types (Active Learning)
// ============================================================================

export type DistanceMetric = z.infer<typeof schemas.DistanceMetricSchema>;

export type SearchSessionTargetTag = z.infer<
  typeof schemas.SearchSessionTargetTagSchema
>;

export type SampleType = z.infer<typeof schemas.SampleTypeSchema>;

export type SearchSession = z.infer<typeof schemas.SearchSessionSchema>;

export type SearchSessionCreate = z.input<
  typeof schemas.SearchSessionCreateSchema
>;

export type SearchProgress = z.infer<typeof schemas.SearchProgressSchema>;

// ============================================================================
// SearchResult Types (Active Learning)
// ============================================================================

export type SearchResult = z.infer<typeof schemas.SearchResultSchema>;

export type SearchResultLabelData = z.input<
  typeof schemas.SearchResultLabelDataSchema
>;

export type BulkLabelRequest = z.input<typeof schemas.BulkLabelRequestSchema>;

export type BulkCurateRequest = z.input<typeof schemas.BulkCurateRequestSchema>;

export type RunIterationRequest = z.input<
  typeof schemas.RunIterationRequestSchema
>;

export type TagScoreDistribution = z.infer<
  typeof schemas.TagScoreDistributionSchema
>;

export type ScoreDistributionResponse = z.infer<
  typeof schemas.ScoreDistributionResponseSchema
>;

export type ExportToAPRequest = z.input<typeof schemas.ExportToAPRequestSchema>;

export type ExportToAPResponse = z.infer<
  typeof schemas.ExportToAPResponseSchema
>;

export type MLProjectAnnotationProject = z.infer<
  typeof schemas.MLProjectAnnotationProjectSchema
>;

// ============================================================================
// CustomModel Types
// ============================================================================

export type CustomModelType = z.infer<typeof schemas.CustomModelTypeSchema>;

export type CustomModelStatus = z.infer<typeof schemas.CustomModelStatusSchema>;

export type CustomModel = z.infer<typeof schemas.CustomModelSchema>;

export type CustomModelCreate = z.input<typeof schemas.CustomModelCreateSchema>;

export type TrainingProgress = z.infer<typeof schemas.TrainingProgressSchema>;

export type TrainingDataSourceType = z.infer<
  typeof schemas.TrainingDataSourceTypeSchema
>;

// ============================================================================
// InferenceBatch Types
// ============================================================================

export type InferenceBatchStatus = z.infer<
  typeof schemas.InferenceBatchStatusSchema
>;

export type InferenceBatch = z.infer<typeof schemas.InferenceBatchSchema>;

export type InferenceBatchCreate = z.input<
  typeof schemas.InferenceBatchCreateSchema
>;

// ============================================================================
// InferencePrediction Types
// ============================================================================

export type InferencePredictionReviewStatus = z.infer<
  typeof schemas.InferencePredictionReviewStatusSchema
>;

export type InferencePrediction = z.infer<
  typeof schemas.InferencePredictionSchema
>;

export type InferencePredictionReview = z.input<
  typeof schemas.InferencePredictionReviewSchema
>;

export type InferenceProgress = z.infer<typeof schemas.InferenceProgressSchema>;

// ============================================================================
// MLProject Dataset Scope Types
// ============================================================================

export type MLProjectDatasetScope = z.infer<
  typeof schemas.MLProjectDatasetScopeSchema
>;

export type MLProjectDatasetScopeCreate = z.input<
  typeof schemas.MLProjectDatasetScopeCreateSchema
>;
