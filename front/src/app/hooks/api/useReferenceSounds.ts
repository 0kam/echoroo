import { useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";

import api from "@/app/api";

import useFilter from "@/lib/hooks/utils/useFilter";
import usePagedQuery from "@/lib/hooks/utils/usePagedQuery";

import type {
  ReferenceSound,
  ReferenceSoundFromXenoCanto,
  ReferenceSoundFromClip,
} from "@/lib/types";
import type { ReferenceSoundFilter } from "@/lib/api/reference_sounds";

const emptyFilter: ReferenceSoundFilter = {};
const _fixed: (keyof ReferenceSoundFilter)[] = [];

/**
 * Custom hook for managing reference sounds for an ML project.
 *
 * This hook encapsulates the logic for querying, creating, deleting,
 * and managing reference sounds including computing embeddings.
 */
export default function useReferenceSounds({
  mlProjectUuid,
  filter: initialFilter = emptyFilter,
  fixed = _fixed,
  pageSize = 10,
  enabled = true,
  onCreateReferenceSound,
  onDeleteReferenceSound,
  onComputeEmbedding,
}: {
  mlProjectUuid: string;
  filter?: ReferenceSoundFilter;
  fixed?: (keyof ReferenceSoundFilter)[];
  pageSize?: number;
  enabled?: boolean;
  onCreateReferenceSound?: (referenceSound: ReferenceSound) => void;
  onDeleteReferenceSound?: (referenceSound: ReferenceSound) => void;
  onComputeEmbedding?: (referenceSound: ReferenceSound) => void;
} = { mlProjectUuid: "" }) {
  const queryClient = useQueryClient();

  const filter = useFilter<ReferenceSoundFilter>({
    defaults: initialFilter,
    fixed,
  });

  const { query, pagination, items, total, queryKey } = usePagedQuery({
    name: `ml_project_${mlProjectUuid}_reference_sounds`,
    queryFn: (params) => api.referenceSounds.getMany(mlProjectUuid, params),
    pageSize,
    filter: filter.filter,
    enabled: enabled && !!mlProjectUuid,
  });

  const createFromXenoCanto = useMutation({
    mutationFn: (data: ReferenceSoundFromXenoCanto) =>
      api.referenceSounds.createFromXenoCanto(mlProjectUuid, data),
    onSuccess: (data) => {
      toast.success("Reference sound created from Xeno-Canto");
      onCreateReferenceSound?.(data);
      query.refetch();
    },
    onError: () => {
      toast.error("Failed to create reference sound");
    },
  });

  const createFromClip = useMutation({
    mutationFn: (data: ReferenceSoundFromClip) =>
      api.referenceSounds.createFromClip(mlProjectUuid, data),
    onSuccess: (data) => {
      toast.success("Reference sound created from clip");
      onCreateReferenceSound?.(data);
      query.refetch();
    },
    onError: () => {
      toast.error("Failed to create reference sound");
    },
  });

  const delete_ = useMutation({
    mutationFn: (uuid: string) =>
      api.referenceSounds.delete(mlProjectUuid, uuid),
    onSuccess: (data) => {
      toast.success("Reference sound deleted");
      onDeleteReferenceSound?.(data);
      query.refetch();
    },
    onError: () => {
      toast.error("Failed to delete reference sound");
    },
  });

  const computeEmbedding = useMutation({
    mutationFn: (uuid: string) =>
      api.referenceSounds.computeEmbedding(mlProjectUuid, uuid),
    onSuccess: (data) => {
      toast.success("Embedding computed");
      onComputeEmbedding?.(data);
      queryClient.invalidateQueries({ queryKey });
    },
    onError: () => {
      toast.error("Failed to compute embedding");
    },
  });

  return {
    ...query,
    items,
    filter,
    pagination,
    total,
    createFromXenoCanto,
    createFromClip,
    delete: delete_,
    computeEmbedding,
  } as const;
}
