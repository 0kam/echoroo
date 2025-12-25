import { AxiosInstance } from "axios";
import { z } from "zod";

import { GetMany, Page } from "@/lib/api/common";
import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

// Filter type for CustomModel
export type CustomModelFilter = {
  status?: types.CustomModelStatus;
};

const DEFAULT_ENDPOINTS = {
  getMany: "/api/v1/ml_projects/detail/custom_models/",
  get: "/api/v1/ml_projects/detail/custom_models/detail/",
  create: "/api/v1/ml_projects/detail/custom_models/",
  delete: "/api/v1/ml_projects/detail/custom_models/detail/",
  train: "/api/v1/ml_projects/detail/custom_models/detail/train/",
  status: "/api/v1/ml_projects/detail/custom_models/detail/status/",
  deploy: "/api/v1/ml_projects/detail/custom_models/detail/deploy/",
  archive: "/api/v1/ml_projects/detail/custom_models/detail/archive/",
};

export function registerCustomModelAPI(
  instance: AxiosInstance,
  endpoints: typeof DEFAULT_ENDPOINTS = DEFAULT_ENDPOINTS,
) {
  const CustomModelFilterSchema = z.object({
    status: schemas.CustomModelStatusSchema.optional(),
  });

  /**
   * Get a paginated list of custom models for an ML project.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param query - Query parameters for filtering and pagination
   * @returns Page of custom models
   */
  async function getMany(
    mlProjectUuid: string,
    query: types.GetMany & CustomModelFilter = {},
  ): Promise<types.Page<types.CustomModel>> {
    const params = GetMany(CustomModelFilterSchema).parse(query);
    const { data } = await instance.get(endpoints.getMany, {
      params: {
        ml_project_uuid: mlProjectUuid,
        limit: params.limit,
        offset: params.offset,
        status__eq: params.status,
      },
    });
    return Page(schemas.CustomModelSchema).parse(data);
  }

  /**
   * Get a single custom model by UUID.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param uuid - The UUID of the custom model
   * @returns The custom model
   */
  async function get(
    mlProjectUuid: string,
    uuid: string,
  ): Promise<types.CustomModel> {
    const { data } = await instance.get(endpoints.get, {
      params: {
        ml_project_uuid: mlProjectUuid,
        custom_model_uuid: uuid,
      },
    });
    return schemas.CustomModelSchema.parse(data);
  }

  /**
   * Create a new custom model.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param data - The custom model data
   * @returns The created custom model
   */
  async function create(
    mlProjectUuid: string,
    data: types.CustomModelCreate,
  ): Promise<types.CustomModel> {
    const body = schemas.CustomModelCreateSchema.parse(data);
    const { data: responseData } = await instance.post(endpoints.create, body, {
      params: { ml_project_uuid: mlProjectUuid },
    });
    return schemas.CustomModelSchema.parse(responseData);
  }

  /**
   * Delete a custom model.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param uuid - The UUID of the custom model
   * @returns The deleted custom model
   */
  async function deleteCustomModel(
    mlProjectUuid: string,
    uuid: string,
  ): Promise<types.CustomModel> {
    const { data } = await instance.delete(endpoints.delete, {
      params: {
        ml_project_uuid: mlProjectUuid,
        custom_model_uuid: uuid,
      },
    });
    return schemas.CustomModelSchema.parse(data);
  }

  /**
   * Start training a custom model.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param modelUuid - The UUID of the custom model
   * @returns The updated custom model
   */
  async function startTraining(
    mlProjectUuid: string,
    modelUuid: string,
  ): Promise<types.CustomModel> {
    const { data } = await instance.post(
      endpoints.train,
      {},
      {
        params: {
          ml_project_uuid: mlProjectUuid,
          custom_model_uuid: modelUuid,
        },
      },
    );
    return schemas.CustomModelSchema.parse(data);
  }

  /**
   * Get the training status of a custom model.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param modelUuid - The UUID of the custom model
   * @returns The training progress
   */
  async function getTrainingStatus(
    mlProjectUuid: string,
    modelUuid: string,
  ): Promise<types.TrainingProgress> {
    const { data } = await instance.get(endpoints.status, {
      params: {
        ml_project_uuid: mlProjectUuid,
        custom_model_uuid: modelUuid,
      },
    });
    return schemas.TrainingProgressSchema.parse(data);
  }

  /**
   * Deploy a trained custom model.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param modelUuid - The UUID of the custom model
   * @returns The updated custom model
   */
  async function deploy(
    mlProjectUuid: string,
    modelUuid: string,
  ): Promise<types.CustomModel> {
    const { data } = await instance.post(
      endpoints.deploy,
      {},
      {
        params: {
          ml_project_uuid: mlProjectUuid,
          custom_model_uuid: modelUuid,
        },
      },
    );
    return schemas.CustomModelSchema.parse(data);
  }

  /**
   * Archive a custom model.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param modelUuid - The UUID of the custom model
   * @returns The updated custom model
   */
  async function archive(
    mlProjectUuid: string,
    modelUuid: string,
  ): Promise<types.CustomModel> {
    const { data } = await instance.post(
      endpoints.archive,
      {},
      {
        params: {
          ml_project_uuid: mlProjectUuid,
          custom_model_uuid: modelUuid,
        },
      },
    );
    return schemas.CustomModelSchema.parse(data);
  }

  return {
    getMany,
    get,
    create,
    delete: deleteCustomModel,
    startTraining,
    getTrainingStatus,
    deploy,
    archive,
  } as const;
}
