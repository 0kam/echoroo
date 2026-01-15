import { AxiosInstance } from "axios";
import { z } from "zod";

import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

type MetadataEndpoints = {
  recorders: string;
  recorder: (id: string) => string;
  licenses: string;
  license: (id: string) => string;
  projects: string;
  project: (id: string) => string;
  projectMembers: (projectId: string) => string;
  projectMember: (projectId: string, userId: string) => string;
  projectMemberRole: (projectId: string, userId: string) => string;
  sites: string;
  site: (id: string) => string;
  siteImages: (siteId: string) => string;
  siteImage: (siteImageId: string) => string;
  siteImageUpload: (siteId: string) => string;
};

const DEFAULT_ENDPOINTS: MetadataEndpoints = {
  recorders: "/api/v1/metadata/recorders",
  recorder: (id: string) => `/api/v1/metadata/recorders/${id}`,
  licenses: "/api/v1/metadata/licenses",
  license: (id: string) => `/api/v1/metadata/licenses/${id}`,
  projects: "/api/v1/metadata/projects",
  project: (id: string) => `/api/v1/metadata/projects/${id}`,
  projectMembers: (projectId: string) =>
    `/api/v1/metadata/projects/${projectId}/members`,
  projectMember: (projectId: string, userId: string) =>
    `/api/v1/metadata/projects/${projectId}/members/${userId}`,
  projectMemberRole: (projectId: string, userId: string) =>
    `/api/v1/metadata/projects/${projectId}/members/${userId}/role`,
  sites: "/api/v1/metadata/sites",
  site: (id: string) => `/api/v1/metadata/sites/${id}`,
  siteImages: (siteId: string) => `/api/v1/metadata/sites/${siteId}/images`,
  siteImage: (siteImageId: string) =>
    `/api/v1/metadata/site_images/${siteImageId}`,
  siteImageUpload: (siteId: string) =>
    `/api/v1/metadata/sites/${siteId}/images/upload`,
};

const searchSchema = z.object({
  search: z.string().optional(),
  project_id: z.string().optional(),
});

const projectQuerySchema = searchSchema.extend({
  is_active: z.boolean().optional(),
});

export function registerMetadataAPI(
  instance: AxiosInstance,
  endpoints: MetadataEndpoints = DEFAULT_ENDPOINTS,
) {
  const recorders = {
    list: async (query: types.MetadataSearch = {}) => {
      const params = searchSchema.parse(query);
      const { data } = await instance.get(endpoints.recorders, { params });
      return z.array(schemas.RecorderSchema).parse(data);
    },
    create: async (payload: types.RecorderCreate) => {
      const body = schemas.RecorderCreateSchema.parse(payload);
      const { data } = await instance.post(endpoints.recorders, body);
      return schemas.RecorderSchema.parse(data);
    },
    update: async (id: string, payload: types.RecorderUpdate) => {
      const body = schemas.RecorderUpdateSchema.parse(payload);
      const { data } = await instance.patch(endpoints.recorder(id), body);
      return schemas.RecorderSchema.parse(data);
    },
    delete: async (id: string) => {
      await instance.delete(endpoints.recorder(id));
    },
  } as const;

  const licenses = {
    list: async (query: types.MetadataSearch = {}) => {
      const params = searchSchema.parse(query);
      const { data } = await instance.get(endpoints.licenses, { params });
      return z.array(schemas.LicenseSchema).parse(data);
    },
    create: async (payload: types.LicenseCreate) => {
      const body = schemas.LicenseCreateSchema.parse(payload);
      const { data } = await instance.post(endpoints.licenses, body);
      return schemas.LicenseSchema.parse(data);
    },
    update: async (id: string, payload: types.LicenseUpdate) => {
      const body = schemas.LicenseUpdateSchema.parse(payload);
      const { data } = await instance.patch(endpoints.license(id), body);
      return schemas.LicenseSchema.parse(data);
    },
    delete: async (id: string) => {
      await instance.delete(endpoints.license(id));
    },
  } as const;

  const projects = {
    list: async (
      query: types.MetadataSearch & { is_active?: boolean } = {},
    ) => {
      const params = projectQuerySchema.parse(query);
      const { data } = await instance.get(endpoints.projects, { params });
      return z.array(schemas.ProjectSchema).parse(data);
    },
    get: async (id: string) => {
      const { data } = await instance.get(endpoints.project(id));
      return schemas.ProjectSchema.parse(data);
    },
    create: async (payload: types.ProjectCreate) => {
      const body = schemas.ProjectCreateSchema.parse(payload);
      const { data } = await instance.post(endpoints.projects, body);
      return schemas.ProjectSchema.parse(data);
    },
    update: async (id: string, payload: types.ProjectUpdate) => {
      const body = schemas.ProjectUpdateSchema.parse(payload);
      const { data } = await instance.patch(endpoints.project(id), body);
      return schemas.ProjectSchema.parse(data);
    },
    delete: async (id: string) => {
      await instance.delete(endpoints.project(id));
    },
  } as const;

  const sites = {
    list: async (query: types.MetadataSearch = {}) => {
      const params = searchSchema.parse(query);
      const { data } = await instance.get(endpoints.sites, { params });
      return z.array(schemas.SiteSchema).parse(data);
    },
    create: async (payload: types.SiteCreate) => {
      const body = schemas.SiteCreateSchema.parse(payload);
      const { data } = await instance.post(endpoints.sites, body);
      return schemas.SiteSchema.parse(data);
    },
    update: async (id: string, payload: types.SiteUpdate) => {
      const body = schemas.SiteUpdateSchema.parse(payload);
      const { data } = await instance.patch(endpoints.site(id), body);
      return schemas.SiteSchema.parse(data);
    },
    delete: async (id: string) => {
      await instance.delete(endpoints.site(id));
    },
  } as const;

  const siteImages = {
    create: async (siteId: string, payload: types.SiteImageCreate) => {
      const body = schemas.SiteImageCreateSchema.parse(
        payload,
      );
      const { data } = await instance.post(endpoints.siteImages(siteId), body);
      return schemas.SiteImageSchema.parse(data);
    },
    update: async (siteImageId: string, payload: types.SiteImageUpdate) => {
      const body = schemas.SiteImageUpdateSchema.parse(payload);
      const { data } = await instance.patch(
        endpoints.siteImage(siteImageId),
        body,
      );
      return schemas.SiteImageSchema.parse(data);
    },
    delete: async (siteImageId: string) => {
      await instance.delete(endpoints.siteImage(siteImageId));
    },
    upload: async (
      siteId: string,
      payload: { site_image_id: string; file: File },
    ) => {
      const body = new FormData();
      body.append("site_image_id", payload.site_image_id);
      body.append("file", payload.file);
      const { data } = await instance.post(
        endpoints.siteImageUpload(siteId),
        body,
        {
          headers: { "Content-Type": "multipart/form-data" },
        },
      );
      return schemas.SiteImageSchema.parse(data);
    },
  } as const;

  const projectMembers = {
    add: async (projectId: string, payload: types.ProjectMemberCreate) => {
      const body = schemas.ProjectMemberCreateSchema.parse(payload);
      const { data } = await instance.post(
        endpoints.projectMembers(projectId),
        body,
      );
      return schemas.ProjectMemberSchema.parse(data);
    },
    remove: async (projectId: string, userId: string) => {
      await instance.delete(endpoints.projectMember(projectId, userId));
    },
    updateRole: async (
      projectId: string,
      userId: string,
      payload: types.ProjectMemberUpdate,
    ) => {
      const body = schemas.ProjectMemberUpdateSchema.parse(payload);
      const { data } = await instance.patch(
        endpoints.projectMemberRole(projectId, userId),
        body,
      );
      return schemas.ProjectMemberSchema.parse(data);
    },
  } as const;

  return {
    recorders,
    licenses,
    projects,
    sites,
    siteImages,
    projectMembers,
  } as const;
}
