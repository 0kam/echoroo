import { AxiosInstance } from "axios";
import { z } from "zod";

import { GetMany, Page } from "@/lib/api/common";
import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

// Filter type for InferenceBatch
export type InferenceBatchFilter = {
  status?: types.InferenceBatchStatus;
};

const DEFAULT_ENDPOINTS = {
  getMany: (mlProjectUuid: string) => `/api/v1/ml_projects/${mlProjectUuid}/inference_batches`,
  get: (mlProjectUuid: string, batchUuid: string) => `/api/v1/ml_projects/${mlProjectUuid}/inference_batches/${batchUuid}`,
  create: (mlProjectUuid: string) => `/api/v1/ml_projects/${mlProjectUuid}/inference_batches`,
  delete: (mlProjectUuid: string, batchUuid: string) => `/api/v1/ml_projects/${mlProjectUuid}/inference_batches/${batchUuid}`,
  start: (mlProjectUuid: string, batchUuid: string) => `/api/v1/ml_projects/${mlProjectUuid}/inference_batches/${batchUuid}/start`,
  cancel: (mlProjectUuid: string, batchUuid: string) => `/api/v1/ml_projects/${mlProjectUuid}/inference_batches/${batchUuid}/cancel`,
  progress: (mlProjectUuid: string, batchUuid: string) => `/api/v1/ml_projects/${mlProjectUuid}/inference_batches/${batchUuid}/progress`,
  predictions: (mlProjectUuid: string, batchUuid: string) => `/api/v1/ml_projects/${mlProjectUuid}/inference_batches/${batchUuid}/predictions`,
  convertToAnnotationProject: (mlProjectUuid: string, batchUuid: string) => `/api/v1/ml_projects/${mlProjectUuid}/inference_batches/${batchUuid}/convert-to-annotation-project`,
};

export function registerInferenceBatchAPI(
  instance: AxiosInstance,
  endpoints: typeof DEFAULT_ENDPOINTS = DEFAULT_ENDPOINTS,
) {
  const InferenceBatchFilterSchema = z.object({
    status: schemas.InferenceBatchStatusSchema.optional(),
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
    const { data } = await instance.get(endpoints.getMany(mlProjectUuid), {
      params: {
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
    const { data } = await instance.get(endpoints.get(mlProjectUuid, uuid));
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
    const { data: responseData } = await instance.post(endpoints.create(mlProjectUuid), body);
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
    const { data } = await instance.delete(endpoints.delete(mlProjectUuid, uuid));
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
    const { data } = await instance.post(endpoints.start(mlProjectUuid, batchUuid), {});
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
    const { data } = await instance.post(endpoints.cancel(mlProjectUuid, batchUuid), {});
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
    const { data } = await instance.get(endpoints.progress(mlProjectUuid, batchUuid));
    return schemas.InferenceProgressSchema.parse(data);
  }

  /**
   * Get predictions for an inference batch.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param batchUuid - The UUID of the inference batch
   * @param query - Query parameters for pagination
   * @returns Page of inference predictions
   */
  async function getPredictions(
    mlProjectUuid: string,
    batchUuid: string,
    query: types.GetMany = {},
  ): Promise<types.Page<types.InferencePrediction>> {
    const params = GetMany(z.object({})).parse(query);
    const { data } = await instance.get(endpoints.predictions(mlProjectUuid, batchUuid), {
      params: {
        limit: params.limit,
        offset: params.offset,
      },
    });
    return Page(schemas.InferencePredictionSchema).parse(data);
  }

  /**
   * Convert inference batch predictions to an annotation project.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param batchUuid - The UUID of the inference batch
   * @param data - The conversion request data
   * @returns The created annotation project
   */
  async function convertToAnnotationProject(
    mlProjectUuid: string,
    batchUuid: string,
    data: types.ConvertToAnnotationProjectRequest,
  ): Promise<types.AnnotationProject> {
    const body = schemas.ConvertToAnnotationProjectRequestSchema.parse(data);
    const { data: responseData } = await instance.post(
      endpoints.convertToAnnotationProject(mlProjectUuid, batchUuid),
      body
    );
    return schemas.AnnotationProjectSchema.parse(responseData);
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
    convertToAnnotationProject,
  } as const;
}
