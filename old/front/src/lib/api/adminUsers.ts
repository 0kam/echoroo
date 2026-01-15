import { AxiosInstance } from "axios";
import { z } from "zod";

import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

type AdminUserEndpoints = {
  base: string;
};

const DEFAULT_ENDPOINTS: AdminUserEndpoints = {
  base: "/api/v1/admin/users",
};

export function registerAdminUsersAPI(
  instance: AxiosInstance,
  endpoints: AdminUserEndpoints = DEFAULT_ENDPOINTS,
) {
  async function list(params?: { limit?: number; offset?: number }) {
    const { data } = await instance.get(endpoints.base + "/", { params });
    return z.array(schemas.SimpleUserSchema).parse(data);
  }

  async function get(id: string) {
    const { data } = await instance.get(`${endpoints.base}/${id}`);
    return schemas.SimpleUserSchema.parse(data);
  }

  async function create(payload: types.UserCreate) {
    const body = schemas.UserCreateSchema.parse(payload);
    const { data } = await instance.post(endpoints.base + "/", body);
    return schemas.SimpleUserSchema.parse(data);
  }

  async function update(id: string, payload: types.AdminUserUpdate) {
    const body = schemas.AdminUserUpdateSchema.parse(payload);
    const { data } = await instance.patch(`${endpoints.base}/${id}`, body);
    return schemas.SimpleUserSchema.parse(data);
  }

  async function remove(id: string) {
    await instance.delete(`${endpoints.base}/${id}`);
  }

  return {
    list,
    get,
    create,
    update,
    delete: remove,
  } as const;
}
