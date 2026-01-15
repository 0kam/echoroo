import { useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";

import api from "@/app/api";

import useFilter from "@/lib/hooks/utils/useFilter";
import usePagedQuery from "@/lib/hooks/utils/usePagedQuery";

import type { MLProject, MLProjectCreate } from "@/lib/types";
import type { MLProjectFilter } from "@/lib/api/ml_projects";

const emptyFilter: MLProjectFilter = {};
const _fixed: (keyof MLProjectFilter)[] = [];

/**
 * Custom hook for managing a paginated list of ML projects.
 *
 * This hook encapsulates the logic for querying ML projects with
 * filtering and pagination support, as well as creating new ML projects.
 */
export default function useMLProjects({
  filter: initialFilter = emptyFilter,
  fixed = _fixed,
  pageSize = 10,
  enabled = true,
  onCreateMLProject,
}: {
  filter?: MLProjectFilter;
  fixed?: (keyof MLProjectFilter)[];
  pageSize?: number;
  enabled?: boolean;
  onCreateMLProject?: (mlProject: MLProject) => void;
} = {}) {
  const filter = useFilter<MLProjectFilter>({
    defaults: initialFilter,
    fixed,
  });

  const { query, pagination, items, total } = usePagedQuery({
    name: "ml_projects",
    queryFn: api.mlProjects.getMany,
    pageSize,
    filter: filter.filter,
    enabled,
  });

  const create = useMutation({
    mutationFn: (data: MLProjectCreate) => api.mlProjects.create(data),
    onSuccess: (data) => {
      toast.success(`ML project "${data.name}" created`);
      onCreateMLProject?.(data);
      query.refetch();
    },
    onError: () => {
      toast.error("Failed to create ML project");
    },
  });

  return {
    ...query,
    items,
    filter,
    pagination,
    total,
    create,
  } as const;
}
