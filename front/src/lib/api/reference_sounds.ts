import { AxiosInstance } from "axios";
import { z } from "zod";

import { GetMany, Page } from "@/lib/api/common";
import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

// Filter type for ReferenceSound
export type ReferenceSoundFilter = {
  is_active?: boolean;
};

const DEFAULT_ENDPOINTS = {
  getMany: "/api/v1/ml_projects/detail/reference_sounds/",
  get: "/api/v1/ml_projects/detail/reference_sounds/detail/",
  createFromXenoCanto: "/api/v1/ml_projects/detail/reference_sounds/from_xeno_canto/",
  createFromClip: "/api/v1/ml_projects/detail/reference_sounds/from_clip/",
  delete: "/api/v1/ml_projects/detail/reference_sounds/detail/",
  computeEmbedding: "/api/v1/ml_projects/detail/reference_sounds/detail/compute_embedding/",
  toggleActive: "/api/v1/ml_projects/detail/reference_sounds/detail/toggle_active/",
};

export function registerReferenceSoundAPI(
  instance: AxiosInstance,
  endpoints: typeof DEFAULT_ENDPOINTS = DEFAULT_ENDPOINTS,
) {
  const ReferenceSoundFilterSchema = z.object({
    is_active: z.boolean().optional(),
  });

  /**
   * Get a paginated list of reference sounds for an ML project.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param query - Query parameters for filtering and pagination
   * @returns Page of reference sounds
   */
  async function getMany(
    mlProjectUuid: string,
    query: types.GetMany & ReferenceSoundFilter = {},
  ): Promise<types.Page<types.ReferenceSound>> {
    const params = GetMany(ReferenceSoundFilterSchema).parse(query);
    const { data } = await instance.get(endpoints.getMany, {
      params: {
        ml_project_uuid: mlProjectUuid,
        limit: params.limit,
        offset: params.offset,
        is_active__eq: params.is_active,
      },
    });
    return Page(schemas.ReferenceSoundSchema).parse(data);
  }

  /**
   * Get a single reference sound by UUID.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param uuid - The UUID of the reference sound
   * @returns The reference sound
   */
  async function get(
    mlProjectUuid: string,
    uuid: string,
  ): Promise<types.ReferenceSound> {
    const { data } = await instance.get(endpoints.get, {
      params: {
        ml_project_uuid: mlProjectUuid,
        reference_sound_uuid: uuid,
      },
    });
    return schemas.ReferenceSoundSchema.parse(data);
  }

  /**
   * Create a reference sound from a Xeno-Canto recording.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param data - The Xeno-Canto source data
   * @returns The created reference sound
   */
  async function createFromXenoCanto(
    mlProjectUuid: string,
    data: types.ReferenceSoundFromXenoCanto,
  ): Promise<types.ReferenceSound> {
    const body = schemas.ReferenceSoundFromXenoCantoSchema.parse(data);
    const { data: responseData } = await instance.post(
      endpoints.createFromXenoCanto,
      body,
      {
        params: { ml_project_uuid: mlProjectUuid },
      },
    );
    return schemas.ReferenceSoundSchema.parse(responseData);
  }

  /**
   * Create a reference sound from an existing clip.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param data - The clip source data
   * @returns The created reference sound
   */
  async function createFromClip(
    mlProjectUuid: string,
    data: types.ReferenceSoundFromClip,
  ): Promise<types.ReferenceSound> {
    const body = schemas.ReferenceSoundFromClipSchema.parse(data);
    const { data: responseData } = await instance.post(
      endpoints.createFromClip,
      body,
      {
        params: { ml_project_uuid: mlProjectUuid },
      },
    );
    return schemas.ReferenceSoundSchema.parse(responseData);
  }

  /**
   * Delete a reference sound.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param uuid - The UUID of the reference sound
   * @returns The deleted reference sound
   */
  async function deleteReferenceSound(
    mlProjectUuid: string,
    uuid: string,
  ): Promise<types.ReferenceSound> {
    const { data } = await instance.delete(endpoints.delete, {
      params: {
        ml_project_uuid: mlProjectUuid,
        reference_sound_uuid: uuid,
      },
    });
    return schemas.ReferenceSoundSchema.parse(data);
  }

  /**
   * Compute embedding for a reference sound.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param uuid - The UUID of the reference sound
   * @returns The updated reference sound with embedding
   */
  async function computeEmbedding(
    mlProjectUuid: string,
    uuid: string,
  ): Promise<types.ReferenceSound> {
    const { data } = await instance.post(
      endpoints.computeEmbedding,
      {},
      {
        params: {
          ml_project_uuid: mlProjectUuid,
          reference_sound_uuid: uuid,
        },
      },
    );
    return schemas.ReferenceSoundSchema.parse(data);
  }

  /**
   * Toggle the active state of a reference sound.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param uuid - The UUID of the reference sound
   * @returns The updated reference sound
   */
  async function toggleActive(
    mlProjectUuid: string,
    uuid: string,
  ): Promise<types.ReferenceSound> {
    const { data } = await instance.post(
      endpoints.toggleActive,
      {},
      {
        params: {
          ml_project_uuid: mlProjectUuid,
          reference_sound_uuid: uuid,
        },
      },
    );
    return schemas.ReferenceSoundSchema.parse(data);
  }

  return {
    getMany,
    get,
    createFromXenoCanto,
    createFromClip,
    delete: deleteReferenceSound,
    computeEmbedding,
    toggleActive,
  } as const;
}
