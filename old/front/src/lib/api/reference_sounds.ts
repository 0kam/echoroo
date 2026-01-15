import { AxiosInstance } from "axios";
import { z } from "zod";

import { GetMany, Page } from "@/lib/api/common";
import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

// Filter type for ReferenceSound
export type ReferenceSoundFilter = {
  is_active?: boolean;
};

// Helper to build endpoints with ml_project_uuid
function buildEndpoints(mlProjectUuid: string) {
  const base = `/api/v1/ml_projects/${mlProjectUuid}/reference_sounds`;
  return {
    getMany: base,
    get: (uuid: string) => `${base}/${uuid}`,
    createFromXenoCanto: `${base}/from_xeno_canto`,
    createFromClip: `${base}/from_clip`,
    update: (uuid: string) => `${base}/${uuid}`,
    delete: (uuid: string) => `${base}/${uuid}`,
    computeEmbedding: (uuid: string) => `${base}/${uuid}/compute_embedding`,
  };
}

export function registerReferenceSoundAPI(instance: AxiosInstance) {
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
    const endpoints = buildEndpoints(mlProjectUuid);
    const { data } = await instance.get(endpoints.getMany, {
      params: {
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
    const endpoints = buildEndpoints(mlProjectUuid);
    const { data } = await instance.get(endpoints.get(uuid));
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
    const endpoints = buildEndpoints(mlProjectUuid);
    const { data: responseData } = await instance.post(
      endpoints.createFromXenoCanto,
      body,
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
    const endpoints = buildEndpoints(mlProjectUuid);
    const { data: responseData } = await instance.post(
      endpoints.createFromClip,
      body,
    );
    return schemas.ReferenceSoundSchema.parse(responseData);
  }

  /**
   * Update a reference sound.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param uuid - The UUID of the reference sound
   * @param data - The update data
   * @returns The updated reference sound
   */
  async function update(
    mlProjectUuid: string,
    uuid: string,
    data: types.ReferenceSoundUpdate,
  ): Promise<types.ReferenceSound> {
    const body = schemas.ReferenceSoundUpdateSchema.parse(data);
    const endpoints = buildEndpoints(mlProjectUuid);
    const { data: responseData } = await instance.patch(
      endpoints.update(uuid),
      body,
    );
    return schemas.ReferenceSoundSchema.parse(responseData);
  }

  /**
   * Toggle the active state of a reference sound.
   *
   * @param mlProjectUuid - The UUID of the ML project
   * @param uuid - The UUID of the reference sound
   * @param isActive - The new active state
   * @returns The updated reference sound
   */
  async function toggleActive(
    mlProjectUuid: string,
    uuid: string,
    isActive: boolean,
  ): Promise<types.ReferenceSound> {
    return update(mlProjectUuid, uuid, { is_active: isActive });
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
    const endpoints = buildEndpoints(mlProjectUuid);
    const { data } = await instance.delete(endpoints.delete(uuid));
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
    const endpoints = buildEndpoints(mlProjectUuid);
    const { data } = await instance.post(endpoints.computeEmbedding(uuid), {});
    return schemas.ReferenceSoundSchema.parse(data);
  }

  return {
    getMany,
    get,
    createFromXenoCanto,
    createFromClip,
    update,
    toggleActive,
    delete: deleteReferenceSound,
    computeEmbedding,
  } as const;
}
