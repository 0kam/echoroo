import { useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";

import api from "@/app/api";

import useFilter from "@/lib/hooks/utils/useFilter";
import usePagedQuery from "@/lib/hooks/utils/usePagedQuery";

import type { AnnotationProject, AnnotationProjectFilter, Dataset } from "@/lib/types";

const _fixed: (keyof AnnotationProjectFilter)[] = ["dataset__eq"];

/**
 * Custom hook for fetching and managing annotation projects for a specific dataset.
 *
 * This hook provides filtered annotation projects based on the dataset uuid,
 * along with pagination, search, and creation functionality.
 */
export default function useDatasetAnnotationProjects({
  dataset,
  pageSize = 10,
  onCreateAnnotationProject,
}: {
  dataset: Dataset;
  pageSize?: number;
  onCreateAnnotationProject?: (annotationProject: AnnotationProject) => void;
}) {
  const filter = useFilter<AnnotationProjectFilter>({
    defaults: {
      dataset__eq: dataset.uuid,
    },
    fixed: _fixed,
  });

  const { query, pagination, items, total } = usePagedQuery({
    name: "annotation_projects",
    queryFn: api.annotationProjects.getMany,
    pageSize,
    filter: filter.filter,
  });

  const create = useMutation({
    mutationFn: api.annotationProjects.create,
    onSuccess: (data) => {
      toast.success(`Annotation project ${data.name} created`);
      onCreateAnnotationProject?.(data);
      query.refetch();
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
