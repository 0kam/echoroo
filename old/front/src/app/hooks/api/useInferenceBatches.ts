import { useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";

import api from "@/app/api";

import useFilter from "@/lib/hooks/utils/useFilter";
import usePagedQuery from "@/lib/hooks/utils/usePagedQuery";

import type { InferenceBatch, InferenceBatchCreate } from "@/lib/types";
import type { InferenceBatchFilter } from "@/lib/api/inference_batches";

const emptyFilter: InferenceBatchFilter = {};
const _fixed: (keyof InferenceBatchFilter)[] = [];

/**
 * Custom hook for managing a paginated list of inference batches
 * for an ML project.
 *
 * This hook encapsulates the logic for querying inference batches
 * with filtering and pagination support, as well as creating
 * and deleting batches.
 */
export default function useInferenceBatches({
  mlProjectUuid,
  filter: initialFilter = emptyFilter,
  fixed = _fixed,
  pageSize = 10,
  enabled = true,
  onCreateInferenceBatch,
  onDeleteInferenceBatch,
}: {
  mlProjectUuid: string;
  filter?: InferenceBatchFilter;
  fixed?: (keyof InferenceBatchFilter)[];
  pageSize?: number;
  enabled?: boolean;
  onCreateInferenceBatch?: (batch: InferenceBatch) => void;
  onDeleteInferenceBatch?: (batch: InferenceBatch) => void;
} = { mlProjectUuid: "" }) {
  const filter = useFilter<InferenceBatchFilter>({
    defaults: initialFilter,
    fixed,
  });

  const { query, pagination, items, total } = usePagedQuery({
    name: `ml_project_${mlProjectUuid}_inference_batches`,
    queryFn: (params) => api.inferenceBatches.getMany(mlProjectUuid, params),
    pageSize,
    filter: filter.filter,
    enabled: enabled && !!mlProjectUuid,
  });

  const create = useMutation({
    mutationFn: (data: InferenceBatchCreate) =>
      api.inferenceBatches.create(mlProjectUuid, data),
    onSuccess: (data) => {
      toast.success(`Inference batch "${data.name}" created`);
      onCreateInferenceBatch?.(data);
      query.refetch();
    },
    onError: () => {
      toast.error("Failed to create inference batch");
    },
  });

  const delete_ = useMutation({
    mutationFn: (batchUuid: string) =>
      api.inferenceBatches.delete(mlProjectUuid, batchUuid),
    onSuccess: (data) => {
      toast.success("Inference batch deleted");
      onDeleteInferenceBatch?.(data);
      query.refetch();
    },
    onError: () => {
      toast.error("Failed to delete inference batch");
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
