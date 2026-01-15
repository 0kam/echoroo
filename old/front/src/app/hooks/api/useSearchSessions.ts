import { useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";

import api from "@/app/api";

import usePagedQuery from "@/lib/hooks/utils/usePagedQuery";

import type { SearchSession, SearchSessionCreate } from "@/lib/types";

/**
 * Custom hook for managing a paginated list of search sessions
 * for an ML project.
 *
 * This hook encapsulates the logic for querying search sessions
 * with pagination support, as well as creating and deleting sessions.
 */
export default function useSearchSessions({
  mlProjectUuid,
  pageSize = 10,
  enabled = true,
  onCreateSearchSession,
  onDeleteSearchSession,
}: {
  mlProjectUuid: string;
  pageSize?: number;
  enabled?: boolean;
  onCreateSearchSession?: (session: SearchSession) => void;
  onDeleteSearchSession?: (session: SearchSession) => void;
} = { mlProjectUuid: "" }) {
  const { query, pagination, items, total } = usePagedQuery({
    name: `ml_project_${mlProjectUuid}_search_sessions`,
    queryFn: (params) => api.searchSessions.getMany(mlProjectUuid, params),
    pageSize,
    filter: {},
    enabled: enabled && !!mlProjectUuid,
  });

  const create = useMutation({
    mutationFn: (data: SearchSessionCreate) =>
      api.searchSessions.create(mlProjectUuid, data),
    onSuccess: (data) => {
      toast.success("Search session created");
      onCreateSearchSession?.(data);
      query.refetch();
    },
    onError: () => {
      toast.error("Failed to create search session");
    },
  });

  const delete_ = useMutation({
    mutationFn: (sessionUuid: string) =>
      api.searchSessions.delete(mlProjectUuid, sessionUuid),
    onSuccess: (data) => {
      toast.success("Search session deleted");
      onDeleteSearchSession?.(data);
      query.refetch();
    },
    onError: () => {
      toast.error("Failed to delete search session");
    },
  });

  return {
    ...query,
    items,
    pagination,
    total,
    create,
    delete: delete_,
  } as const;
}
