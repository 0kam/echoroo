import { useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";

import api from "@/app/api";

import useFilter from "@/lib/hooks/utils/useFilter";
import usePagedQuery from "@/lib/hooks/utils/usePagedQuery";

import type { CustomModel, CustomModelCreate } from "@/lib/types";
import type { CustomModelFilter } from "@/lib/api/custom_models";

const emptyFilter: CustomModelFilter = {};
const _fixed: (keyof CustomModelFilter)[] = [];

/**
 * Custom hook for managing a paginated list of custom models
 * for an ML project.
 *
 * This hook encapsulates the logic for querying custom models
 * with filtering and pagination support, as well as creating
 * and deleting models.
 */
export default function useCustomModels({
  mlProjectUuid,
  filter: initialFilter = emptyFilter,
  fixed = _fixed,
  pageSize = 10,
  enabled = true,
  onCreateCustomModel,
  onDeleteCustomModel,
}: {
  mlProjectUuid: string;
  filter?: CustomModelFilter;
  fixed?: (keyof CustomModelFilter)[];
  pageSize?: number;
  enabled?: boolean;
  onCreateCustomModel?: (model: CustomModel) => void;
  onDeleteCustomModel?: (model: CustomModel) => void;
} = { mlProjectUuid: "" }) {
  const filter = useFilter<CustomModelFilter>({
    defaults: initialFilter,
    fixed,
  });

  const { query, pagination, items, total } = usePagedQuery({
    name: `ml_project_${mlProjectUuid}_custom_models`,
    queryFn: (params) => api.customModels.getMany(mlProjectUuid, params),
    pageSize,
    filter: filter.filter,
    enabled: enabled && !!mlProjectUuid,
  });

  const create = useMutation({
    mutationFn: (data: CustomModelCreate) =>
      api.customModels.create(mlProjectUuid, data),
    onSuccess: (data) => {
      toast.success(`Custom model "${data.name}" created`);
      onCreateCustomModel?.(data);
      query.refetch();
    },
    onError: () => {
      toast.error("Failed to create custom model");
    },
  });

  const delete_ = useMutation({
    mutationFn: (modelUuid: string) =>
      api.customModels.delete(mlProjectUuid, modelUuid),
    onSuccess: (data) => {
      toast.success("Custom model deleted");
      onDeleteCustomModel?.(data);
      query.refetch();
    },
    onError: () => {
      toast.error("Failed to delete custom model");
    },
  });

  return {
    ...query,
    items,
    filter,
    pagination,
    total,
    create,
    delete: delete_,
  } as const;
}
