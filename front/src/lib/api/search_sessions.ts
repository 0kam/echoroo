import { AxiosInstance } from "axios";
import { z } from "zod";

import { GetMany, Page } from "@/lib/api/common";
import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

// Filter type for SearchResult with Active Learning fields
export type SearchResultFilter = {
  assigned_tag_id?: number;
  is_negative?: boolean;
  is_uncertain?: boolean;
  is_skipped?: boolean;
  sample_type?: types.SampleType;
  is_labeled?: boolean;
  iteration_added?: number;
};

// Helper to build endpoints with ml_project_uuid and optional search_session_uuid
function buildEndpoints(mlProjectUuid: string, searchSessionUuid?: string) {
  const base = `/api/v1/ml_projects/${mlProjectUuid}/search_sessions`;
  const sessionBase = searchSessionUuid ? `${base}/${searchSessionUuid}` : base;

  return {
    getMany: base,
    get: sessionBase,
    create: base,
    delete: sessionBase,
    execute: `${sessionBase}/execute`,
    runIteration: `${sessionBase}/run_iteration`,
    progress: `${sessionBase}/progress`,
    results: `${sessionBase}/results`,
    labelResult: (resultUuid: string) => `${sessionBase}/results/${resultUuid}/label`,
    bulkLabel: `${sessionBase}/bulk_label`,
    bulkCurate: `${sessionBase}/bulk_curate`,
    exportToAnnotationProject: `${sessionBase}/export_to_annotation_project`,
    scoreDistribution: `${sessionBase}/score_distribution`,
    finalize: `${sessionBase}/finalize`,
  };
}

export function registerSearchSessionAPI(
  instance: AxiosInstance,
) {
  const SearchResultFilterSchema = z.object({
    assigned_tag_id: z.number().int().optional(),
    is_negative: z.boolean().optional(),
    is_uncertain: z.boolean().optional(),
    is_skipped: z.boolean().optional(),
    sample_type: schemas.SampleTypeSchema.optional(),
    is_labeled: z.boolean().optional(),
    iteration_added: z.number().int().optional(),
  });

  /**
   * Get a paginated list of search sessions for an ML project.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param query - Query parameters for pagination
   * @returns Page of search sessions
   */
  async function getMany(
    mlProjectUuid: string,
    query: types.GetMany = {},
  ): Promise<types.Page<types.SearchSession>> {
    const params = GetMany(z.object({})).parse(query);
    const endpoints = buildEndpoints(mlProjectUuid);
    const { data } = await instance.get(endpoints.getMany, {
      params: {
        limit: params.limit,
        offset: params.offset,
      },
    });
    return Page(schemas.SearchSessionSchema).parse(data);
  }

  /**
   * Get a single search session by UUID.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param uuid - The UUID of the search session
   * @returns The search session
   */
  async function get(
    mlProjectUuid: string,
    uuid: string,
  ): Promise<types.SearchSession> {
    const endpoints = buildEndpoints(mlProjectUuid, uuid);
    const { data } = await instance.get(endpoints.get);
    return schemas.SearchSessionSchema.parse(data);
  }

  /**
   * Create a new search session with Active Learning parameters.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param data - The search session data with Active Learning parameters
   * @returns The created search session
   */
  async function create(
    mlProjectUuid: string,
    data: types.SearchSessionCreate,
  ): Promise<types.SearchSession> {
    const body = schemas.SearchSessionCreateSchema.parse(data);
    const endpoints = buildEndpoints(mlProjectUuid);
    const { data: responseData } = await instance.post(endpoints.create, body);
    return schemas.SearchSessionSchema.parse(responseData);
  }

  /**
   * Delete a search session.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param uuid - The UUID of the search session
   * @returns The deleted search session
   */
  async function deleteSearchSession(
    mlProjectUuid: string,
    uuid: string,
  ): Promise<types.SearchSession> {
    const endpoints = buildEndpoints(mlProjectUuid, uuid);
    const { data } = await instance.delete(endpoints.delete);
    return schemas.SearchSessionSchema.parse(data);
  }

  /**
   * Execute initial sampling for a search session.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @returns The updated search session
   */
  async function execute(
    mlProjectUuid: string,
    sessionUuid: string,
  ): Promise<types.SearchSession> {
    const endpoints = buildEndpoints(mlProjectUuid, sessionUuid);
    const { data } = await instance.post(endpoints.execute, {});
    return schemas.SearchSessionSchema.parse(data);
  }

  /**
   * Run an active learning iteration to add new samples based on current labels.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @param params - Optional iteration parameters (uncertainty range, sample count)
   * @returns The updated search session with new samples
   */
  async function runIteration(
    mlProjectUuid: string,
    sessionUuid: string,
    params?: types.RunIterationRequest,
  ): Promise<types.SearchSession> {
    const body = params ? schemas.RunIterationRequestSchema.parse(params) : {};
    const endpoints = buildEndpoints(mlProjectUuid, sessionUuid);
    const { data } = await instance.post(endpoints.runIteration, body);
    return schemas.SearchSessionSchema.parse(data);
  }

  /**
   * Get the progress of a search session.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @returns The search progress with tag counts
   */
  async function getProgress(
    mlProjectUuid: string,
    sessionUuid: string,
  ): Promise<types.SearchProgress> {
    const endpoints = buildEndpoints(mlProjectUuid, sessionUuid);
    const { data } = await instance.get(endpoints.progress);
    return schemas.SearchProgressSchema.parse(data);
  }

  /**
   * Get search results for a session with Active Learning filter support.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @param query - Query parameters for filtering and pagination
   * @returns Page of search results
   */
  async function getResults(
    mlProjectUuid: string,
    sessionUuid: string,
    query: types.GetMany & SearchResultFilter = {},
  ): Promise<types.Page<types.SearchResult>> {
    const params = GetMany(SearchResultFilterSchema).parse(query);
    const endpoints = buildEndpoints(mlProjectUuid, sessionUuid);
    const { data } = await instance.get(endpoints.results, {
      params: {
        limit: params.limit,
        offset: params.offset,
        assigned_tag_id: params.assigned_tag_id,
        is_negative: params.is_negative,
        is_uncertain: params.is_uncertain,
        is_skipped: params.is_skipped,
        sample_type: params.sample_type,
        is_labeled: params.is_labeled,
        iteration_added: params.iteration_added,
      },
    });
    return Page(schemas.SearchResultSchema).parse(data);
  }

  /**
   * Label a search result with Active Learning label data.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @param resultUuid - The UUID of the search result
   * @param data - The label data (assigned_tag_id, is_negative, is_uncertain, is_skipped)
   * @returns The updated search result
   */
  async function labelResult(
    mlProjectUuid: string,
    sessionUuid: string,
    resultUuid: string,
    data: types.SearchResultLabelData,
  ): Promise<types.SearchResult> {
    const body = schemas.SearchResultLabelDataSchema.parse(data);
    const endpoints = buildEndpoints(mlProjectUuid, sessionUuid);
    const { data: responseData } = await instance.post(endpoints.labelResult(resultUuid), body);
    return schemas.SearchResultSchema.parse(responseData);
  }

  /**
   * Bulk label multiple search results with Active Learning labels.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @param data - The bulk label request with label_data
   * @returns The updated count
   */
  async function bulkLabel(
    mlProjectUuid: string,
    sessionUuid: string,
    data: types.BulkLabelRequest,
  ): Promise<{ updated_count: number }> {
    const body = schemas.BulkLabelRequestSchema.parse(data);
    const endpoints = buildEndpoints(mlProjectUuid, sessionUuid);
    const { data: responseData } = await instance.post(endpoints.bulkLabel, body);
    return z.object({ updated_count: z.number().int().nonnegative() }).parse(responseData);
  }


  /**
   * Bulk curate multiple search results by assigning a tag.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @param data - The bulk curate request with assigned_tag_id
   * @returns The updated count
   */
  async function bulkCurate(
    mlProjectUuid: string,
    sessionUuid: string,
    data: types.BulkCurateRequest,
  ): Promise<{ updated_count: number }> {
    const body = schemas.BulkCurateRequestSchema.parse(data);
    const endpoints = buildEndpoints(mlProjectUuid, sessionUuid);
    const { data: responseData } = await instance.post(endpoints.bulkCurate, body);
    return z.object({ updated_count: z.number().int().nonnegative() }).parse(responseData);
  }

  /**
   * Export search session results to an annotation project.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @param data - The export request
   * @returns The export response with annotation project details
   */
  async function exportToAnnotationProject(
    mlProjectUuid: string,
    sessionUuid: string,
    data: types.ExportToAPRequest,
  ): Promise<types.ExportToAPResponse> {
    const body = schemas.ExportToAPRequestSchema.parse(data);
    const endpoints = buildEndpoints(mlProjectUuid, sessionUuid);
    const { data: responseData } = await instance.post(
      endpoints.exportToAnnotationProject,
      body,
    );
    return schemas.ExportToAPResponseSchema.parse(responseData);
  }

  /**
   * Get score distribution for all target tags across iterations.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @returns The score distribution response with histograms per tag and iteration
   */
  async function getScoreDistribution(
    mlProjectUuid: string,
    sessionUuid: string,
  ): Promise<types.ScoreDistributionResponse> {
    const endpoints = buildEndpoints(mlProjectUuid, sessionUuid);
    const { data } = await instance.get(endpoints.scoreDistribution);
    return schemas.ScoreDistributionResponseSchema.parse(data);
  }

  /**
   * Finalize a search session by creating a custom model and optionally an annotation project.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @param data - The finalize request with model details
   * @returns The finalize response with custom model and annotation project details
   */
  async function finalizeSearchSession(
    mlProjectUuid: string,
    sessionUuid: string,
    data: types.FinalizeRequest,
  ): Promise<types.FinalizeResponse> {
    const body = schemas.FinalizeRequestSchema.parse(data);
    const endpoints = buildEndpoints(mlProjectUuid, sessionUuid);
    const { data: responseData } = await instance.post(endpoints.finalize, body);
    return schemas.FinalizeResponseSchema.parse(responseData);
  }

  return {
    getMany,
    get,
    create,
    delete: deleteSearchSession,
    execute,
    runIteration,
    getProgress,
    getResults,
    labelResult,
    bulkLabel,
    bulkCurate,
    exportToAnnotationProject,
    getScoreDistribution,
    finalize: finalizeSearchSession,
  } as const;
}
