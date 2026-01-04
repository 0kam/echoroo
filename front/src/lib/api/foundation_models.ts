"use client";

import { AxiosInstance } from "axios";
import { z } from "zod";

import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

import { Page } from "./common";

const DEFAULT_ENDPOINTS = {
  list: "/api/v1/foundation_models/",
  queueStatus: "/api/v1/foundation_models/queue-status",
  datasetSummary: (uuid: string) =>
    `/api/v1/foundation_models/datasets/${uuid}/summary/`,
  runs: "/api/v1/foundation_models/runs/",
  run: (uuid: string) => `/api/v1/foundation_models/runs/${uuid}`,
  runCancel: (uuid: string) => `/api/v1/foundation_models/runs/${uuid}/cancel`,
  runProgress: (uuid: string) =>
    `/api/v1/foundation_models/runs/${uuid}/progress`,
  runSpecies: (uuid: string) =>
    `/api/v1/foundation_models/runs/${uuid}/species/`,
  runDetections: (uuid: string) =>
    `/api/v1/foundation_models/runs/${uuid}/detections`,
  runDetectionsSummary: (uuid: string) =>
    `/api/v1/foundation_models/runs/${uuid}/detections/summary`,
  runDetectionReview: (runUuid: string, clipPredictionUuid: string) =>
    `/api/v1/foundation_models/runs/${runUuid}/detections/${clipPredictionUuid}/review`,
  runDetectionsBulkReview: (runUuid: string) =>
    `/api/v1/foundation_models/runs/${runUuid}/detections/bulk-review`,
  runConvertToAnnotationProject: (runUuid: string) =>
    `/api/v1/foundation_models/runs/${runUuid}/convert-to-annotation-project`,
};

const ListRunsQuerySchema = z.object({
  dataset_uuid: z.string().uuid().optional(),
  foundation_model_slug: z.string().optional(),
  status: z.string().optional(),
  limit: z.number().int().gte(0).optional(),
  offset: z.number().int().gte(0).optional(),
});

export type DetectionFilter = {
  species_tag_id?: number;
  min_confidence?: number;
  max_confidence?: number;
  review_status?: types.FoundationModelDetectionReviewStatus;
};

export function registerFoundationModelAPI(instance: AxiosInstance) {
  /**
   * List all available foundation models.
   */
  async function list(): Promise<types.FoundationModel[]> {
    const { data } = await instance.get(DEFAULT_ENDPOINTS.list);
    return z.array(schemas.FoundationModelSchema).parse(data);
  }

  /**
   * Get the current job queue status.
   */
  async function getQueueStatus(): Promise<types.JobQueueStatus> {
    const { data } = await instance.get(DEFAULT_ENDPOINTS.queueStatus);
    return schemas.JobQueueStatusSchema.parse(data);
  }

  /**
   * Get a summary of foundation model runs for a dataset.
   */
  async function getDatasetSummary(
    datasetUuid: string,
  ): Promise<types.DatasetFoundationModelSummary[]> {
    const { data } = await instance.get(
      DEFAULT_ENDPOINTS.datasetSummary(datasetUuid),
    );
    return z.array(schemas.DatasetFoundationModelSummarySchema).parse(data);
  }

  /**
   * List foundation model runs, optionally filtered by dataset.
   */
  async function listRuns(query: {
    dataset_uuid?: string;
    foundation_model_slug?: string;
    status?: types.FoundationModelRunStatus;
    limit?: number;
    offset?: number;
  } = {}): Promise<types.Page<types.FoundationModelRun>> {
    const params = ListRunsQuerySchema.parse(query);
    const { data } = await instance.get(DEFAULT_ENDPOINTS.runs, { params });
    return Page(schemas.FoundationModelRunSchema).parse(data);
  }

  /**
   * Create a new foundation model run.
   */
  async function createRun(
    payload: types.FoundationModelRunCreate,
  ): Promise<types.FoundationModelRun> {
    const body = schemas.FoundationModelRunCreateSchema.parse(payload);
    const { data } = await instance.post(DEFAULT_ENDPOINTS.runs, body);
    return schemas.FoundationModelRunSchema.parse(data);
  }

  /**
   * Get a single foundation model run by UUID.
   */
  async function getRun(runUuid: string): Promise<types.FoundationModelRun> {
    const { data } = await instance.get(DEFAULT_ENDPOINTS.run(runUuid));
    return schemas.FoundationModelRunSchema.parse(data);
  }

  /**
   * Cancel a running foundation model run.
   */
  async function cancelRun(
    runUuid: string,
  ): Promise<types.FoundationModelRun> {
    const { data } = await instance.post(DEFAULT_ENDPOINTS.runCancel(runUuid));
    return schemas.FoundationModelRunSchema.parse(data);
  }

  /**
   * Get progress for a foundation model run.
   */
  async function getRunProgress(
    runUuid: string,
  ): Promise<types.FoundationModelRunProgress> {
    const { data } = await instance.get(DEFAULT_ENDPOINTS.runProgress(runUuid));
    return schemas.FoundationModelRunProgressSchema.parse(data);
  }

  /**
   * Get species data for a foundation model run (legacy endpoint).
   */
  async function getRunSpecies(
    runUuid: string,
  ): Promise<types.FoundationModelRun> {
    const { data } = await instance.get(DEFAULT_ENDPOINTS.runSpecies(runUuid));
    return schemas.FoundationModelRunSchema.parse(data);
  }

  /**
   * Get detection results for a foundation model run.
   */
  async function getDetections(
    runUuid: string,
    query: types.GetMany & DetectionFilter = {},
  ): Promise<types.Page<types.FoundationModelDetection>> {
    const { data } = await instance.get(
      DEFAULT_ENDPOINTS.runDetections(runUuid),
      {
        params: {
          limit: query.limit ?? 50,
          offset: query.offset ?? 0,
          species_tag_id: query.species_tag_id,
          min_confidence: query.min_confidence,
          max_confidence: query.max_confidence,
          review_status: query.review_status,
        },
      },
    );
    return Page(schemas.FoundationModelDetectionSchema).parse(data);
  }

  /**
   * Get detection summary for a foundation model run.
   */
  async function getDetectionSummary(
    runUuid: string,
  ): Promise<types.FoundationModelDetectionSummary> {
    const { data } = await instance.get(
      DEFAULT_ENDPOINTS.runDetectionsSummary(runUuid),
    );
    return schemas.FoundationModelDetectionSummarySchema.parse(data);
  }

  /**
   * Review a single detection.
   */
  async function reviewDetection(
    runUuid: string,
    clipPredictionUuid: string,
    reviewData: types.FoundationModelDetectionReviewUpdate,
  ): Promise<types.FoundationModelDetectionReview> {
    const body =
      schemas.FoundationModelDetectionReviewUpdateSchema.parse(reviewData);
    const { data } = await instance.post(
      DEFAULT_ENDPOINTS.runDetectionReview(runUuid, clipPredictionUuid),
      body,
    );
    return schemas.FoundationModelDetectionReviewSchema.parse(data);
  }

  /**
   * Bulk review multiple detections.
   */
  async function bulkReviewDetections(
    runUuid: string,
    clipPredictionUuids: string[],
    reviewData: types.FoundationModelDetectionReviewUpdate,
  ): Promise<types.BulkReviewResponse> {
    const body =
      schemas.FoundationModelDetectionReviewUpdateSchema.parse(reviewData);
    const { data } = await instance.post(
      DEFAULT_ENDPOINTS.runDetectionsBulkReview(runUuid),
      body,
      {
        params: {
          clip_prediction_uuids: clipPredictionUuids,
        },
      },
    );
    return schemas.BulkReviewResponseSchema.parse(data);
  }

  /**
   * Convert a foundation model run to an annotation project.
   */
  async function convertToAnnotationProject(
    runUuid: string,
    payload: {
      name: string;
      description?: string;
      include_only_filtered?: boolean;
      species_filter_application_uuid?: string;
    },
  ): Promise<types.ConvertToAnnotationProjectResponse> {
    const { data } = await instance.post(
      DEFAULT_ENDPOINTS.runConvertToAnnotationProject(runUuid),
      payload,
    );
    return schemas.ConvertToAnnotationProjectResponseSchema.parse(data);
  }

  return {
    list,
    getQueueStatus,
    getDatasetSummary,
    listRuns,
    createRun,
    getRun,
    cancelRun,
    getRunProgress,
    getRunSpecies,
    getDetections,
    getDetectionSummary,
    reviewDetection,
    bulkReviewDetections,
    convertToAnnotationProject,
  };
}
