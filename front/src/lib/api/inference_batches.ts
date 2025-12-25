import { AxiosInstance } from "axios";
import { z } from "zod";

import { GetMany, Page } from "@/lib/api/common";
import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

// Filter type for InferenceBatch
export type InferenceBatchFilter = {
  status?: types.InferenceBatchStatus;
};

// Filter type for InferencePrediction
export type InferencePredictionFilter = {
  review_status?: types.InferencePredictionReviewStatus;
};

const DEFAULT_ENDPOINTS = {
  getMany: "/api/v1/ml_projects/detail/inference_batches/",
  get: "/api/v1/ml_projects/detail/inference_batches/detail/",
  create: "/api/v1/ml_projects/detail/inference_batches/",
  delete: "/api/v1/ml_projects/detail/inference_batches/detail/",
  start: "/api/v1/ml_projects/detail/inference_batches/detail/start/",
  cancel: "/api/v1/ml_projects/detail/inference_batches/detail/cancel/",
  progress: "/api/v1/ml_projects/detail/inference_batches/detail/progress/",
  predictions: "/api/v1/ml_projects/detail/inference_batches/detail/predictions/",
  review: "/api/v1/ml_projects/detail/inference_batches/detail/predictions/review/",
  bulkReview: "/api/v1/ml_projects/detail/inference_batches/detail/predictions/bulk_review/",
};

export function registerInferenceBatchAPI(
  instance: AxiosInstance,
  endpoints: typeof DEFAULT_ENDPOINTS = DEFAULT_ENDPOINTS,
) {
  const InferenceBatchFilterSchema = z.object({
    status: schemas.InferenceBatchStatusSchema.optional(),
  });

  const InferencePredictionFilterSchema = z.object({
    review_status: schemas.InferencePredictionReviewStatusSchema.optional(),
  });

  /**
   * Get a paginated list of inference batches for an ML project.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param query - Query parameters for filtering and pagination
   * @returns Page of inference batches
   */
  async function getMany(
    mlProjectUuid: string,
    query: types.GetMany & InferenceBatchFilter = {},
  ): Promise<types.Page<types.InferenceBatch>> {
    const params = GetMany(InferenceBatchFilterSchema).parse(query);
    const { data } = await instance.get(endpoints.getMany, {
      params: {
        ml_project_uuid: mlProjectUuid,
        limit: params.limit,
        offset: params.offset,
        status__eq: params.status,
      },
    });
    return Page(schemas.InferenceBatchSchema).parse(data);
  }

  /**
   * Get a single inference batch by UUID.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param uuid - The UUID of the inference batch
   * @returns The inference batch
   */
  async function get(
    mlProjectUuid: string,
    uuid: string,
  ): Promise<types.InferenceBatch> {
    const { data } = await instance.get(endpoints.get, {
      params: {
        ml_project_uuid: mlProjectUuid,
        inference_batch_uuid: uuid,
      },
    });
    return schemas.InferenceBatchSchema.parse(data);
  }

  /**
   * Create a new inference batch.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param data - The inference batch data
   * @returns The created inference batch
   */
  async function create(
    mlProjectUuid: string,
    data: types.InferenceBatchCreate,
  ): Promise<types.InferenceBatch> {
    const body = schemas.InferenceBatchCreateSchema.parse(data);
    const { data: responseData } = await instance.post(endpoints.create, body, {
      params: { ml_project_uuid: mlProjectUuid },
    });
    return schemas.InferenceBatchSchema.parse(responseData);
  }

  /**
   * Delete an inference batch.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param uuid - The UUID of the inference batch
   * @returns The deleted inference batch
   */
  async function deleteInferenceBatch(
    mlProjectUuid: string,
    uuid: string,
  ): Promise<types.InferenceBatch> {
    const { data } = await instance.delete(endpoints.delete, {
      params: {
        ml_project_uuid: mlProjectUuid,
        inference_batch_uuid: uuid,
      },
    });
    return schemas.InferenceBatchSchema.parse(data);
  }

  /**
   * Start an inference batch.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param batchUuid - The UUID of the inference batch
   * @returns The updated inference batch
   */
  async function start(
    mlProjectUuid: string,
    batchUuid: string,
  ): Promise<types.InferenceBatch> {
    const { data } = await instance.post(
      endpoints.start,
      {},
      {
        params: {
          ml_project_uuid: mlProjectUuid,
          inference_batch_uuid: batchUuid,
        },
      },
    );
    return schemas.InferenceBatchSchema.parse(data);
  }

  /**
   * Cancel a running inference batch.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param batchUuid - The UUID of the inference batch
   * @returns The updated inference batch
   */
  async function cancel(
    mlProjectUuid: string,
    batchUuid: string,
  ): Promise<types.InferenceBatch> {
    const { data } = await instance.post(
      endpoints.cancel,
      {},
      {
        params: {
          ml_project_uuid: mlProjectUuid,
          inference_batch_uuid: batchUuid,
        },
      },
    );
    return schemas.InferenceBatchSchema.parse(data);
  }

  /**
   * Get the progress of an inference batch.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param batchUuid - The UUID of the inference batch
   * @returns The inference progress
   */
  async function getProgress(
    mlProjectUuid: string,
    batchUuid: string,
  ): Promise<types.InferenceProgress> {
    const { data } = await instance.get(endpoints.progress, {
      params: {
        ml_project_uuid: mlProjectUuid,
        inference_batch_uuid: batchUuid,
      },
    });
    return schemas.InferenceProgressSchema.parse(data);
  }

  /**
   * Get predictions for an inference batch.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param batchUuid - The UUID of the inference batch
   * @param query - Query parameters for filtering and pagination
   * @returns Page of inference predictions
   */
  async function getPredictions(
    mlProjectUuid: string,
    batchUuid: string,
    query: types.GetMany & InferencePredictionFilter = {},
  ): Promise<types.Page<types.InferencePrediction>> {
    const params = GetMany(InferencePredictionFilterSchema).parse(query);
    const { data } = await instance.get(endpoints.predictions, {
      params: {
        ml_project_uuid: mlProjectUuid,
        inference_batch_uuid: batchUuid,
        limit: params.limit,
        offset: params.offset,
        review_status__eq: params.review_status,
      },
    });
    return Page(schemas.InferencePredictionSchema).parse(data);
  }

  /**
   * Review an inference prediction.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param batchUuid - The UUID of the inference batch
   * @param predictionUuid - The UUID of the prediction
   * @param data - The review data
   * @returns The updated prediction
   */
  async function reviewPrediction(
    mlProjectUuid: string,
    batchUuid: string,
    predictionUuid: string,
    data: types.InferencePredictionReview,
  ): Promise<types.InferencePrediction> {
    const body = schemas.InferencePredictionReviewSchema.parse(data);
    const { data: responseData } = await instance.post(endpoints.review, body, {
      params: {
        ml_project_uuid: mlProjectUuid,
        inference_batch_uuid: batchUuid,
        inference_prediction_uuid: predictionUuid,
      },
    });
    return schemas.InferencePredictionSchema.parse(responseData);
  }

  /**
   * Bulk review multiple predictions.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param batchUuid - The UUID of the inference batch
   * @param data - The bulk review request
   * @returns The updated count
   */
  async function bulkReview(
    mlProjectUuid: string,
    batchUuid: string,
    data: {
      prediction_uuids: string[];
      review_status: types.InferencePredictionReviewStatus;
    },
  ): Promise<{ updated_count: number }> {
    const { data: responseData } = await instance.post(endpoints.bulkReview, data, {
      params: {
        ml_project_uuid: mlProjectUuid,
        inference_batch_uuid: batchUuid,
      },
    });
    return z.object({ updated_count: z.number().int().nonnegative() }).parse(responseData);
  }

  return {
    getMany,
    get,
    create,
    delete: deleteInferenceBatch,
    start,
    cancel,
    getProgress,
    getPredictions,
    reviewPrediction,
    bulkReview,
  } as const;
}
