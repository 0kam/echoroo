import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";

import api from "@/app/api";

import type {
  License,
  LicenseCreate,
  LicenseUpdate,
  MetadataSearch,
  Project,
  ProjectCreate,
  ProjectUpdate,
  ProjectMemberCreate,
  ProjectMemberUpdate,
  Recorder,
  RecorderCreate,
  RecorderUpdate,
  Site,
  SiteCreate,
  SiteImageCreate,
  SiteImageUpdate,
  SiteUpdate,
} from "@/lib/types";

type MetadataMessages<Item> = {
  create: (item: Item) => string;
  update: (item: Item) => string;
  delete: string;
};

type CrudApi<Item, CreatePayload, UpdatePayload, Query> = {
  list: (query: Query) => Promise<Item[]>;
  create: (payload: CreatePayload) => Promise<Item>;
  update: (id: string, payload: UpdatePayload) => Promise<Item>;
  delete: (id: string) => Promise<void>;
};

function createMetadataCrudHook<
  Item,
  CreatePayload,
  UpdatePayload,
  Query extends MetadataSearch = MetadataSearch,
>(
  resourceKey: string,
  resource: CrudApi<Item, CreatePayload, UpdatePayload, Query>,
  messages: MetadataMessages<Item>,
) {
  return function useMetadataResource(query: Query = {} as Query) {
    const client = useQueryClient();
    const listQuery = useQuery({
      queryKey: ["metadata", resourceKey, query],
      queryFn: () => resource.list(query),
      staleTime: 30_000,
    });

    const refresh = () =>
      client.invalidateQueries({ queryKey: ["metadata", resourceKey] });

    const create = useMutation({
      mutationFn: (payload: CreatePayload) => resource.create(payload),
      onSuccess: (item) => {
        toast.success(messages.create(item));
        refresh();
      },
    });

    const update = useMutation({
      mutationFn: ({
        id,
        payload,
      }: {
        id: string;
        payload: UpdatePayload;
      }) => resource.update(id, payload),
      onSuccess: (item) => {
        toast.success(messages.update(item));
        refresh();
      },
    });

    const remove = useMutation({
      mutationFn: (id: string) => resource.delete(id),
      onSuccess: () => {
        toast.success(messages.delete);
        refresh();
      },
    });

    return {
      query: listQuery,
      create,
      update,
      remove,
      refresh,
    } as const;
  };
}

const useRecorderCrud = createMetadataCrudHook<
  Recorder,
  RecorderCreate,
  RecorderUpdate
>("recorders", api.metadata.recorders, {
  create: (recorder) => `レコーダー ${recorder.recorder_id} を追加しました`,
  update: (recorder) => `レコーダー ${recorder.recorder_id} を更新しました`,
  delete: "レコーダーを削除しました",
});

export function useMetadataRecorders(query: MetadataSearch = {}) {
  return useRecorderCrud(query);
}

const useLicenseCrud = createMetadataCrudHook<
  License,
  LicenseCreate,
  LicenseUpdate
>("licenses", api.metadata.licenses, {
  create: (license) => `ライセンス ${license.license_id} を追加しました`,
  update: (license) => `ライセンス ${license.license_id} を更新しました`,
  delete: "ライセンスを削除しました",
});

export function useMetadataLicenses(query: MetadataSearch = {}) {
  return useLicenseCrud(query);
}

type ProjectQuery = MetadataSearch & { is_active?: boolean };

const useProjectCrud = createMetadataCrudHook<
  Project,
  ProjectCreate,
  ProjectUpdate,
  ProjectQuery
>("projects", api.metadata.projects, {
  create: (project) => `プロジェクト ${project.project_id} を追加しました`,
  update: (project) => `プロジェクト ${project.project_id} を更新しました`,
  delete: "プロジェクトを削除しました",
});

export function useMetadataProjects(query: ProjectQuery = {}) {
  return useProjectCrud(query);
}

export function useProject(projectId: string) {
  const client = useQueryClient();

  const query = useQuery({
    queryKey: ["metadata", "projects", projectId],
    queryFn: () => api.metadata.projects.get(projectId),
    staleTime: 30_000,
  });

  const refresh = () =>
    client.invalidateQueries({ queryKey: ["metadata", "projects", projectId] });

  const update = useMutation({
    mutationFn: (payload: ProjectUpdate) =>
      api.metadata.projects.update(projectId, payload),
    onSuccess: (project) => {
      toast.success(`プロジェクト ${project.project_id} を更新しました`);
      refresh();
    },
  });

  const addMember = useMutation({
    mutationFn: (payload: ProjectMemberCreate) =>
      api.metadata.projectMembers.add(projectId, payload),
    onSuccess: () => {
      toast.success("メンバーを追加しました");
      refresh();
    },
  });

  const removeMember = useMutation({
    mutationFn: (userId: string) =>
      api.metadata.projectMembers.remove(projectId, userId),
    onSuccess: () => {
      toast.success("メンバーを削除しました");
      refresh();
    },
  });

  const updateMemberRole = useMutation({
    mutationFn: ({ userId, payload }: { userId: string; payload: ProjectMemberUpdate }) =>
      api.metadata.projectMembers.updateRole(projectId, userId, payload),
    onSuccess: () => {
      toast.success("メンバーの役割を更新しました");
      refresh();
    },
  });

  return {
    query,
    update,
    addMember,
    removeMember,
    updateMemberRole,
    refresh,
  } as const;
}

const useSiteCrud = createMetadataCrudHook<Site, SiteCreate, SiteUpdate>(
  "sites",
  api.metadata.sites,
  {
    create: (site) => `サイト ${site.site_id} を追加しました`,
    update: (site) => `サイト ${site.site_id} を更新しました`,
    delete: "サイトを削除しました",
  },
);

export function useMetadataSites(query: MetadataSearch = {}) {
  const crud = useSiteCrud(query);
  const { query: siteQuery, create, update, remove, refresh } = crud;

  const addImage = useMutation({
    mutationFn: ({
      siteId,
      payload,
    }: {
      siteId: string;
      payload: SiteImageCreate;
    }) => api.metadata.siteImages.create(siteId, payload),
    onSuccess: (image) => {
      toast.success(`画像 ${image.site_image_id} を追加しました`);
      refresh();
    },
  });

  const updateImage = useMutation({
    mutationFn: ({
      siteImageId,
      payload,
    }: {
      siteImageId: string;
      payload: SiteImageUpdate;
    }) => api.metadata.siteImages.update(siteImageId, payload),
    onSuccess: (image) => {
      toast.success(`画像 ${image.site_image_id} を更新しました`);
      refresh();
    },
  });

  const removeImage = useMutation({
    mutationFn: (siteImageId: string) =>
      api.metadata.siteImages.delete(siteImageId),
    onSuccess: () => {
      toast.success("サイト画像を削除しました");
      refresh();
    },
  });

  const uploadImage = useMutation({
    mutationFn: ({
      siteId,
      payload,
    }: {
      siteId: string;
      payload: { site_image_id: string; file: File };
    }) => api.metadata.siteImages.upload(siteId, payload),
    onSuccess: (image) => {
      toast.success(`画像 ${image.site_image_id} をアップロードしました`);
      refresh();
    },
  });

  return {
    query: siteQuery,
    create,
    update,
    remove,
    refresh,
    addImage,
    updateImage,
    removeImage,
    uploadImage,
  } as const;
}
