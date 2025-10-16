import { AxiosInstance } from "axios";
import { z } from "zod";

import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

import { GetMany, Page } from "./common";

type GroupEndpoints = {
  base: string;
  me: string;
  userGroups: (userId: string) => string;
  members: (groupId: number) => string;
  member: (groupId: number, userId: string) => string;
};

const DEFAULT_ENDPOINTS: GroupEndpoints = {
  base: "/api/v1/groups",
  me: "/api/v1/groups/me",
  userGroups: (userId: string) => `/api/v1/users/${userId}/groups`,
  members: (groupId: number) => `/api/v1/groups/${groupId}/members`,
  member: (groupId: number, userId: string) =>
    `/api/v1/groups/${groupId}/members/${userId}`,
};

export function registerGroupsAPI(
  instance: AxiosInstance,
  endpoints: GroupEndpoints = DEFAULT_ENDPOINTS,
) {
  async function list(
    query: types.GetMany = {},
  ): Promise<types.Page<types.Group>> {
    const params = GetMany(z.object({})).parse(query);
    const { data } = await instance.get(endpoints.base, { params });
    return Page(schemas.GroupSchema).parse(data);
  }

  async function create(data: types.GroupCreate): Promise<types.Group> {
    const body = schemas.GroupCreateSchema.parse(data);
    const { data: response } = await instance.post(endpoints.base, body);
    return schemas.GroupSchema.parse(response);
  }

  async function update(
    groupId: number,
    data: types.GroupUpdate,
  ): Promise<types.Group> {
    const body = schemas.GroupUpdateSchema.parse(data);
    const { data: response } = await instance.patch(
      `${endpoints.base}/${groupId}`,
      body,
    );
    return schemas.GroupSchema.parse(response);
  }

  async function remove(groupId: number): Promise<void> {
    await instance.delete(`${endpoints.base}/${groupId}`);
  }

  async function detail(groupId: number): Promise<types.GroupDetail> {
    const { data } = await instance.get(`${endpoints.base}/${groupId}`);
    return schemas.GroupDetailSchema.parse(data);
  }

  async function myGroups(): Promise<types.GroupDetail[]> {
    const { data } = await instance.get(endpoints.me);
    return z.array(schemas.GroupDetailSchema).parse(data);
  }

  async function listUserGroups(
    userId: string,
  ): Promise<types.GroupDetail[]> {
    const { data } = await instance.get(endpoints.userGroups(userId));
    return z.array(schemas.GroupDetailSchema).parse(data);
  }

  async function addMember(
    groupId: number,
    payload: types.GroupMembershipCreate,
  ): Promise<types.GroupMembership> {
    const body = schemas.GroupMembershipCreateSchema.parse(payload);
    const { data } = await instance.post(endpoints.members(groupId), body);
    return schemas.GroupMembershipSchema.parse(data);
  }

  async function updateMember(
    groupId: number,
    userId: string,
    payload: types.GroupMembershipUpdate,
  ): Promise<types.GroupMembership> {
    const body = schemas.GroupMembershipUpdateSchema.parse(payload);
    const { data } = await instance.patch(
      endpoints.member(groupId, userId),
      body,
    );
    return schemas.GroupMembershipSchema.parse(data);
  }

  async function removeMember(groupId: number, userId: string): Promise<void> {
    await instance.delete(endpoints.member(groupId, userId));
  }

  return {
    list,
    create,
    update,
    delete: remove,
    detail,
    mine: myGroups,
    listUserGroups,
    addMember,
    updateMember,
    removeMember,
  } as const;
}
