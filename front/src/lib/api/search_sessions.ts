import { AxiosInstance } from "axios";
import { z } from "zod";

import { GetMany, Page } from "@/lib/api/common";
import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

// Filter type for SearchResult
export type SearchResultFilter = {
  label?: types.SearchResultLabel;
};

const DEFAULT_ENDPOINTS = {
  getMany: "/api/v1/ml_projects/detail/search_sessions/",
  get: "/api/v1/ml_projects/detail/search_sessions/detail/",
  create: "/api/v1/ml_projects/detail/search_sessions/",
  delete: "/api/v1/ml_projects/detail/search_sessions/detail/",
  execute: "/api/v1/ml_projects/detail/search_sessions/detail/execute/",
  progress: "/api/v1/ml_projects/detail/search_sessions/detail/progress/",
  results: "/api/v1/ml_projects/detail/search_sessions/detail/results/",
  labelResult: "/api/v1/ml_projects/detail/search_sessions/detail/results/label/",
  bulkLabel: "/api/v1/ml_projects/detail/search_sessions/detail/bulk_label/",
  markComplete: "/api/v1/ml_projects/detail/search_sessions/detail/mark_complete/",
  bulkCurate: "/api/v1/ml_projects/detail/search_sessions/detail/bulk_curate/",
  exportToAnnotationProject: "/api/v1/ml_projects/detail/search_sessions/detail/export_to_annotation_project/",
};

export function registerSearchSessionAPI(
  instance: AxiosInstance,
  endpoints: typeof DEFAULT_ENDPOINTS = DEFAULT_ENDPOINTS,
) {
  const SearchResultFilterSchema = z.object({
    label: schemas.SearchResultLabelSchema.optional(),
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
    const { data } = await instance.get(endpoints.getMany, {
      params: {
        ml_project_uuid: mlProjectUuid,
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
    const { data } = await instance.get(endpoints.get, {
      params: {
        ml_project_uuid: mlProjectUuid,
        search_session_uuid: uuid,
      },
    });
    return schemas.SearchSessionSchema.parse(data);
  }

  /**
   * Create a new search session.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param data - The search session data
   * @returns The created search session
   */
  async function create(
    mlProjectUuid: string,
    data: types.SearchSessionCreate,
  ): Promise<types.SearchSession> {
    const body = schemas.SearchSessionCreateSchema.parse(data);
    const { data: responseData } = await instance.post(endpoints.create, body, {
      params: { ml_project_uuid: mlProjectUuid },
    });
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
    const { data } = await instance.delete(endpoints.delete, {
      params: {
        ml_project_uuid: mlProjectUuid,
        search_session_uuid: uuid,
      },
    });
    return schemas.SearchSessionSchema.parse(data);
  }

  /**
   * Execute a search session.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @returns The updated search session
   */
  async function execute(
    mlProjectUuid: string,
    sessionUuid: string,
  ): Promise<types.SearchSession> {
    const { data } = await instance.post(
      endpoints.execute,
      {},
      {
        params: {
          ml_project_uuid: mlProjectUuid,
          search_session_uuid: sessionUuid,
        },
      },
    );
    return schemas.SearchSessionSchema.parse(data);
  }

  /**
   * Get the progress of a search session.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @returns The search progress
   */
  async function getProgress(
    mlProjectUuid: string,
    sessionUuid: string,
  ): Promise<types.SearchProgress> {
    const { data } = await instance.get(endpoints.progress, {
      params: {
        ml_project_uuid: mlProjectUuid,
        search_session_uuid: sessionUuid,
      },
    });
    return schemas.SearchProgressSchema.parse(data);
  }

  /**
   * Get search results for a session.
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
    const { data } = await instance.get(endpoints.results, {
      params: {
        ml_project_uuid: mlProjectUuid,
        search_session_uuid: sessionUuid,
        limit: params.limit,
        offset: params.offset,
        label__eq: params.label,
      },
    });
    return Page(schemas.SearchResultSchema).parse(data);
  }

  /**
   * Label a search result.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @param resultUuid - The UUID of the search result
   * @param data - The label update data
   * @returns The updated search result
   */
  async function labelResult(
    mlProjectUuid: string,
    sessionUuid: string,
    resultUuid: string,
    data: types.SearchResultLabelUpdate,
  ): Promise<types.SearchResult> {
    const body = schemas.SearchResultLabelUpdateSchema.parse(data);
    const { data: responseData } = await instance.post(endpoints.labelResult, body, {
      params: {
        ml_project_uuid: mlProjectUuid,
        search_session_uuid: sessionUuid,
        search_result_uuid: resultUuid,
      },
    });
    return schemas.SearchResultSchema.parse(responseData);
  }

  /**
   * Bulk label multiple search results.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @param data - The bulk label request
   * @returns The updated count
   */
  async function bulkLabel(
    mlProjectUuid: string,
    sessionUuid: string,
    data: types.BulkLabelRequest,
  ): Promise<{ updated_count: number }> {
    const body = schemas.BulkLabelRequestSchema.parse(data);
    const { data: responseData } = await instance.post(endpoints.bulkLabel, body, {
      params: {
        ml_project_uuid: mlProjectUuid,
        search_session_uuid: sessionUuid,
      },
    });
    return z.object({ updated_count: z.number().int().nonnegative() }).parse(responseData);
  }

  /**
   * Mark a search session as labeling complete.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @returns The updated search session
   */
  async function markComplete(
    mlProjectUuid: string,
    sessionUuid: string,
  ): Promise<types.SearchSession> {
    const { data } = await instance.post(
      endpoints.markComplete,
      {},
      {
        params: {
          ml_project_uuid: mlProjectUuid,
          search_session_uuid: sessionUuid,
        },
      },
    );
    return schemas.SearchSessionSchema.parse(data);
  }

  /**
   * Bulk curate multiple search results with curation-specific labels.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @param data - The bulk curate request
   * @returns The updated count
   */
  async function bulkCurate(
    mlProjectUuid: string,
    sessionUuid: string,
    data: types.BulkCurateRequest,
  ): Promise<{ updated_count: number }> {
    const body = schemas.BulkCurateRequestSchema.parse(data);
    const { data: responseData } = await instance.post(endpoints.bulkCurate, body, {
      params: {
        ml_project_uuid: mlProjectUuid,
        search_session_uuid: sessionUuid,
      },
    });
    return z.object({ updated_count: z.number().int().nonnegative() }).parse(responseData);
  }

  /**
   * Export search session results to an annotation project.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param sessionUuid - The UUID of the search session
   * @param data - The export request
   * @returns The created annotation project info
   */
  async function exportToAnnotationProject(
    mlProjectUuid: string,
    sessionUuid: string,
    data: types.ExportToAPRequest,
  ): Promise<types.MLProjectAnnotationProject> {
    const body = schemas.ExportToAPRequestSchema.parse(data);
    const { data: responseData } = await instance.post(
      endpoints.exportToAnnotationProject,
      body,
      {
        params: {
          ml_project_uuid: mlProjectUuid,
          search_session_uuid: sessionUuid,
        },
      },
    );
    return schemas.MLProjectAnnotationProjectSchema.parse(responseData);
  }

  return {
    getMany,
    get,
    create,
    delete: deleteSearchSession,
    execute,
    getProgress,
    getResults,
    labelResult,
    bulkLabel,
    markComplete,
    bulkCurate,
    exportToAnnotationProject,
  } as const;
}
