import { AxiosInstance } from "axios";
import { z } from "zod";

import { GetMany, Page } from "@/lib/api/common";
import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

// Filter type for MLProject
export type MLProjectFilter = {
  dataset_id?: number;
  project_id?: string;
  status?: types.MLProjectStatus;
};

const DEFAULT_ENDPOINTS = {
  getMany: "/api/v1/ml_projects/",
  get: "/api/v1/ml_projects/",  // UUID appended as path parameter
  create: "/api/v1/ml_projects/",
  update: "/api/v1/ml_projects/",  // UUID appended as path parameter
  delete: "/api/v1/ml_projects/",  // UUID appended as path parameter
  addTag: "/api/v1/ml_projects/",  // UUID/tags appended as path
  removeTag: "/api/v1/ml_projects/",  // UUID/tags/tag_id appended as path
  annotationProjects: "/api/v1/ml_projects/",  // UUID/annotation_projects appended as path
};

export function registerMLProjectAPI(
  instance: AxiosInstance,
  endpoints: typeof DEFAULT_ENDPOINTS = DEFAULT_ENDPOINTS,
) {
  /**
   * Get a paginated list of ML projects.
   *
   * @param query - Query parameters for filtering and pagination
   * @returns Page of ML projects
   */
  async function getMany(
    query: types.GetMany & MLProjectFilter = {},
  ): Promise<types.Page<types.MLProject>> {
    const params = GetMany(schemas.MLProjectFilterSchema).parse(query);
    const { data } = await instance.get(endpoints.getMany, {
      params: {
        limit: params.limit,
        offset: params.offset,
        sort_by: params.sort_by,
        dataset_id__eq: params.dataset_id,
        status__eq: params.status,
      },
    });
    return Page(schemas.MLProjectSchema).parse(data);
  }

  /**
   * Get a single ML project by UUID.
   *
   * @param uuid - The UUID of the ML project
   * @returns The ML project
   */
  async function get(uuid: string): Promise<types.MLProject> {
    const { data } = await instance.get(`${endpoints.get}${uuid}`);
    return schemas.MLProjectSchema.parse(data);
  }

  /**
   * Create a new ML project.
   *
   * @param data - The ML project data
   * @returns The created ML project
   */
  async function create(data: types.MLProjectCreate): Promise<types.MLProject> {
    const body = schemas.MLProjectCreateSchema.parse(data);
    const { data: responseData } = await instance.post(endpoints.create, body);
    return schemas.MLProjectSchema.parse(responseData);
  }

  /**
   * Update an ML project.
   *
   * @param mlProject - The ML project to update
   * @param data - The update data
   * @returns The updated ML project
   */
  async function update(
    mlProject: types.MLProject,
    data: types.MLProjectUpdate,
  ): Promise<types.MLProject> {
    const body = schemas.MLProjectUpdateSchema.parse(data);
    const { data: responseData } = await instance.patch(
      `${endpoints.update}${mlProject.uuid}`,
      body,
    );
    return schemas.MLProjectSchema.parse(responseData);
  }

  /**
   * Delete an ML project.
   *
   * @param mlProject - The ML project to delete
   * @returns The deleted ML project
   */
  async function deleteMLProject(
    mlProject: types.MLProject,
  ): Promise<types.MLProject> {
    const { data } = await instance.delete(
      `${endpoints.delete}${mlProject.uuid}`,
    );
    return schemas.MLProjectSchema.parse(data);
  }

  /**
   * Add a target tag to an ML project.
   *
   * @param mlProject - The ML project
   * @param tag - The tag to add
   * @returns The updated ML project
   */
  async function addTag(
    mlProject: types.MLProject,
    tag: types.Tag,
  ): Promise<types.MLProject> {
    const { data } = await instance.post(
      `${endpoints.addTag}${mlProject.uuid}/tags`,
      {},
      {
        params: { tag_id: tag.id },
      },
    );
    return schemas.MLProjectSchema.parse(data);
  }

  /**
   * Remove a target tag from an ML project.
   *
   * @param mlProject - The ML project
   * @param tag - The tag to remove
   * @returns The updated ML project
   */
  async function removeTag(
    mlProject: types.MLProject,
    tag: types.Tag,
  ): Promise<types.MLProject> {
    const { data } = await instance.delete(
      `${endpoints.removeTag}${mlProject.uuid}/tags/${tag.id}`,
    );
    return schemas.MLProjectSchema.parse(data);
  }

  // ============================================================================
  // Dataset Scopes
  // ============================================================================

  /**
   * Get all dataset scopes for an ML project.
   *
   * @param uuid - The UUID of the ML project
   * @returns Array of dataset scopes
   */
  async function listDatasetScopes(
    uuid: string,
  ): Promise<types.MLProjectDatasetScope[]> {
    const { data } = await instance.get(
      `${endpoints.get}${uuid}/dataset_scopes`,
    );
    return z.array(schemas.MLProjectDatasetScopeSchema).parse(data);
  }

  /**
   * Add a dataset scope to an ML project.
   *
   * @param uuid - The UUID of the ML project
   * @param data - The dataset scope data
   * @returns The created dataset scope
   */
  async function addDatasetScope(
    uuid: string,
    data: types.MLProjectDatasetScopeCreate,
  ): Promise<types.MLProjectDatasetScope> {
    const body = schemas.MLProjectDatasetScopeCreateSchema.parse(data);
    const { data: responseData } = await instance.post(
      `${endpoints.get}${uuid}/dataset_scopes`,
      body,
    );
    return schemas.MLProjectDatasetScopeSchema.parse(responseData);
  }

  /**
   * Remove a dataset scope from an ML project.
   *
   * @param uuid - The UUID of the ML project
   * @param scopeUuid - The UUID of the dataset scope to remove
   * @returns The deleted dataset scope
   */
  async function removeDatasetScope(
    uuid: string,
    scopeUuid: string,
  ): Promise<types.MLProjectDatasetScope> {
    const { data } = await instance.delete(
      `${endpoints.get}${uuid}/dataset_scopes/${scopeUuid}`,
    );
    return schemas.MLProjectDatasetScopeSchema.parse(data);
  }

  // ============================================================================
  // Annotation Projects for ML Project
  // ============================================================================

  /**
   * Get all annotation projects created from an ML project.
   *
   * @param uuid - The UUID of the ML project
   * @returns Array of annotation projects
   */
  async function listAnnotationProjects(
    uuid: string,
  ): Promise<types.MLProjectAnnotationProject[]> {
    const { data } = await instance.get(
      `${endpoints.annotationProjects}${uuid}/annotation_projects`,
    );
    return z.array(schemas.MLProjectAnnotationProjectSchema).parse(data);
  }

  return {
    getMany,
    get,
    create,
    update,
    delete: deleteMLProject,
    addTag,
    removeTag,
    datasetScopes: {
      list: listDatasetScopes,
      add: addDatasetScope,
      remove: removeDatasetScope,
    },
    annotationProjects: {
      list: listAnnotationProjects,
    },
  } as const;
}
