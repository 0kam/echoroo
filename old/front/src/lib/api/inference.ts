import { AxiosInstance } from "axios";
import { z } from "zod";

import { GetMany, Page } from "@/lib/api/common";
import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

const DEFAULT_ENDPOINTS = {
  getMany: "/api/v1/inference/jobs/",
  getJob: "/api/v1/inference/jobs/detail/",
  createDatasetJob: "/api/v1/inference/jobs/dataset/",
  createRecordingJob: "/api/v1/inference/jobs/recording/",
  cancelJob: "/api/v1/inference/jobs/cancel/",
  searchSimilar: "/api/v1/inference/search/similar/",
  getRandomClips: "/api/v1/inference/search/random/",
};

export function registerInferenceAPI(
  instance: AxiosInstance,
  endpoints: typeof DEFAULT_ENDPOINTS = DEFAULT_ENDPOINTS,
) {
  /**
   * Get a paginated list of inference jobs.
   *
   * @param query - Query parameters for filtering and pagination
   * @returns Page of inference jobs
   */
  async function getInferenceJobs(
    query: types.GetMany & types.InferenceJobFilter = {},
  ): Promise<types.Page<types.InferenceJob>> {
    const params = GetMany(schemas.InferenceJobFilterSchema).parse(query);
    const { data } = await instance.get(endpoints.getMany, {
      params: {
        limit: params.limit,
        offset: params.offset,
        sort_by: params.sort_by,
        status__eq: params.status,
        model_name__eq: params.model_name,
        dataset_uuid__eq: params.dataset_uuid,
        recording_uuid__eq: params.recording_uuid,
      },
    });
    return Page(schemas.InferenceJobSchema).parse(data);
  }

  /**
   * Get a single inference job by UUID.
   *
   * @param uuid - The UUID of the inference job
   * @returns The inference job
   */
  async function getInferenceJob(uuid: string): Promise<types.InferenceJob> {
    const { data } = await instance.get(endpoints.getJob, {
      params: { job_uuid: uuid },
    });
    return schemas.InferenceJobSchema.parse(data);
  }

  /**
   * Create an inference job for a dataset.
   *
   * @param request - The request containing dataset UUID and config
   * @returns The created inference job
   */
  async function createDatasetInferenceJob(
    request: types.CreateDatasetInferenceJob,
  ): Promise<types.InferenceJob> {
    const body = schemas.CreateDatasetInferenceJobSchema.parse(request);
    const { data } = await instance.post(endpoints.createDatasetJob, body);
    return schemas.InferenceJobSchema.parse(data);
  }

  /**
   * Create an inference job for a single recording.
   *
   * @param request - The request containing recording UUID and config
   * @returns The created inference job
   */
  async function createRecordingInferenceJob(
    request: types.CreateRecordingInferenceJob,
  ): Promise<types.InferenceJob> {
    const body = schemas.CreateRecordingInferenceJobSchema.parse(request);
    const { data } = await instance.post(endpoints.createRecordingJob, body);
    return schemas.InferenceJobSchema.parse(data);
  }

  /**
   * Cancel a running or pending inference job.
   *
   * @param uuid - The UUID of the inference job to cancel
   * @returns The cancelled inference job
   */
  async function cancelInferenceJob(uuid: string): Promise<types.InferenceJob> {
    const { data } = await instance.post(
      endpoints.cancelJob,
      {},
      {
        params: { job_uuid: uuid },
      },
    );
    return schemas.InferenceJobSchema.parse(data);
  }

  /**
   * Search for clips similar to a given clip using embedding similarity.
   *
   * @param request - The search request parameters
   * @returns Search results with similar clips
   */
  async function searchSimilarClips(
    request: types.SearchSimilarClipsRequest,
  ): Promise<types.SearchSimilarClipsResponse> {
    const params = schemas.SearchSimilarClipsRequestSchema.parse(request);
    const { data } = await instance.get(endpoints.searchSimilar, {
      params: {
        clip_uuid: params.clip_uuid,
        model_run_uuid: params.model_run_uuid,
        dataset_uuid: params.dataset_uuid,
        limit: params.limit,
        offset: params.offset,
        min_similarity: params.min_similarity,
      },
    });
    return schemas.SearchSimilarClipsResponseSchema.parse(data);
  }

  /**
   * Get random clips from embeddings for exploration.
   *
   * @param request - The request parameters
   * @returns Random clips with embeddings
   */
  async function getRandomClips(
    request: types.GetRandomClipsRequest,
  ): Promise<types.GetRandomClipsResponse> {
    const params = schemas.GetRandomClipsRequestSchema.parse(request);
    const { data } = await instance.get(endpoints.getRandomClips, {
      params: {
        model_run_uuid: params.model_run_uuid,
        dataset_uuid: params.dataset_uuid,
        count: params.count,
      },
    });
    return schemas.GetRandomClipsResponseSchema.parse(data);
  }

  return {
    getJobs: getInferenceJobs,
    getJob: getInferenceJob,
    createDatasetJob: createDatasetInferenceJob,
    createRecordingJob: createRecordingInferenceJob,
    cancel: cancelInferenceJob,
    searchSimilar: searchSimilarClips,
    getRandomClips,
  } as const;
}
