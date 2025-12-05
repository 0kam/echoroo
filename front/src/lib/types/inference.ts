import { z } from "zod";

import * as schemas from "@/lib/schemas";

export type InferenceModelName = z.infer<
  typeof schemas.InferenceModelNameSchema
>;

export type InferenceJobStatus = z.infer<
  typeof schemas.InferenceJobStatusSchema
>;

export type InferenceConfig = z.infer<typeof schemas.InferenceConfigSchema>;

export type InferenceJob = z.infer<typeof schemas.InferenceJobSchema>;

export type SearchResultItem = z.infer<typeof schemas.SearchResultItemSchema>;

export type CreateDatasetInferenceJob = z.input<
  typeof schemas.CreateDatasetInferenceJobSchema
>;

export type CreateRecordingInferenceJob = z.input<
  typeof schemas.CreateRecordingInferenceJobSchema
>;

export type SearchSimilarClipsRequest = z.input<
  typeof schemas.SearchSimilarClipsRequestSchema
>;

export type SearchSimilarClipsResponse = z.infer<
  typeof schemas.SearchSimilarClipsResponseSchema
>;

export type GetRandomClipsRequest = z.input<
  typeof schemas.GetRandomClipsRequestSchema
>;

export type GetRandomClipsResponse = z.infer<
  typeof schemas.GetRandomClipsResponseSchema
>;

export type InferenceJobFilter = z.input<
  typeof schemas.InferenceJobFilterSchema
>;
