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

// ============================================================================
// SearchSession Types
// ============================================================================

export type SearchResultLabel = z.infer<typeof schemas.SearchResultLabelSchema>;

export type SearchSession = z.infer<typeof schemas.SearchSessionSchema>;

export type SearchSessionCreate = z.input<
  typeof schemas.SearchSessionCreateSchema
>;

export type SearchProgress = z.infer<typeof schemas.SearchProgressSchema>;

// ============================================================================
// SearchResult Types
// ============================================================================

export type SearchResult = z.infer<typeof schemas.SearchResultSchema>;

export type SearchResultLabelUpdate = z.input<
  typeof schemas.SearchResultLabelUpdateSchema
>;

export type BulkLabelRequest = z.input<typeof schemas.BulkLabelRequestSchema>;

// ============================================================================
// CustomModel Types
// ============================================================================

export type CustomModelType = z.infer<typeof schemas.CustomModelTypeSchema>;

export type CustomModelStatus = z.infer<typeof schemas.CustomModelStatusSchema>;

export type CustomModel = z.infer<typeof schemas.CustomModelSchema>;

export type CustomModelCreate = z.input<typeof schemas.CustomModelCreateSchema>;

export type TrainingProgress = z.infer<typeof schemas.TrainingProgressSchema>;

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
