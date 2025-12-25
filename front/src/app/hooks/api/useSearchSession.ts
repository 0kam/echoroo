import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import toast from "react-hot-toast";

import api from "@/app/api";

import useFilter from "@/lib/hooks/utils/useFilter";
import usePagedQuery from "@/lib/hooks/utils/usePagedQuery";

import type {
  SearchSession,
  SearchProgress,
  SearchResult,
  SearchResultLabel,
  SearchResultLabelUpdate,
  BulkLabelRequest,
} from "@/lib/types";
import type { SearchResultFilter } from "@/lib/api/search_sessions";

const emptyResultFilter: SearchResultFilter = {};
const _fixed: (keyof SearchResultFilter)[] = [];

/**
 * Custom hook for managing a single search session.
 *
 * This hook encapsulates the logic for querying a search session,
 * executing searches, managing results with pagination, labeling
 * results, and bulk labeling operations.
 */
export default function useSearchSession({
  mlProjectUuid,
  sessionUuid,
  enabled = true,
  resultPageSize = 20,
  resultFilter: initialResultFilter = emptyResultFilter,
  resultFilterFixed = _fixed,
  progressPollingInterval,
  onExecute,
  onLabelResult,
  onBulkLabel,
  onMarkComplete,
  onError,
}: {
  mlProjectUuid: string;
  sessionUuid: string;
  enabled?: boolean;
  resultPageSize?: number;
  resultFilter?: SearchResultFilter;
  resultFilterFixed?: (keyof SearchResultFilter)[];
  progressPollingInterval?: number;
  onExecute?: (session: SearchSession) => void;
  onLabelResult?: (result: SearchResult) => void;
  onBulkLabel?: (count: number) => void;
  onMarkComplete?: (session: SearchSession) => void;
  onError?: (error: AxiosError) => void;
}) {
  const queryClient = useQueryClient();

  // Main session query
  const sessionQuery = useQuery<SearchSession, AxiosError>({
    queryKey: ["search_session", mlProjectUuid, sessionUuid],
    queryFn: () => api.searchSessions.get(mlProjectUuid, sessionUuid),
    enabled: enabled && !!mlProjectUuid && !!sessionUuid,
  });

  // Progress query with optional polling
  const progressQuery = useQuery<SearchProgress, AxiosError>({
    queryKey: ["search_session", mlProjectUuid, sessionUuid, "progress"],
    queryFn: () => api.searchSessions.getProgress(mlProjectUuid, sessionUuid),
    enabled: enabled && !!mlProjectUuid && !!sessionUuid,
    refetchInterval: progressPollingInterval,
  });

  // Result filter
  const resultFilter = useFilter<SearchResultFilter>({
    defaults: initialResultFilter,
    fixed: resultFilterFixed,
  });

  // Results with pagination
  const results = usePagedQuery({
    name: `search_session_${sessionUuid}_results`,
    queryFn: (params) =>
      api.searchSessions.getResults(mlProjectUuid, sessionUuid, params),
    pageSize: resultPageSize,
    filter: resultFilter.filter,
    enabled: enabled && !!mlProjectUuid && !!sessionUuid,
  });

  // Execute search mutation
  const execute = useMutation({
    mutationFn: () => api.searchSessions.execute(mlProjectUuid, sessionUuid),
    onSuccess: (data) => {
      toast.success("Search started");
      onExecute?.(data);
      queryClient.invalidateQueries({
        queryKey: ["search_session", mlProjectUuid, sessionUuid],
      });
    },
    onError: (error: AxiosError) => {
      toast.error("Failed to start search");
      onError?.(error);
    },
  });

  // Label result mutation
  const labelResult = useMutation({
    mutationFn: ({
      resultUuid,
      data,
    }: {
      resultUuid: string;
      data: SearchResultLabelUpdate;
    }) =>
      api.searchSessions.labelResult(
        mlProjectUuid,
        sessionUuid,
        resultUuid,
        data,
      ),
    onSuccess: (data) => {
      onLabelResult?.(data);
      results.query.refetch();
    },
    onError: (error: AxiosError) => {
      toast.error("Failed to label result");
      onError?.(error);
    },
  });

  // Bulk label mutation
  const bulkLabel = useMutation({
    mutationFn: (data: BulkLabelRequest) =>
      api.searchSessions.bulkLabel(mlProjectUuid, sessionUuid, data),
    onSuccess: (data) => {
      toast.success(`Labeled ${data.updated_count} results`);
      onBulkLabel?.(data.updated_count);
      results.query.refetch();
    },
    onError: (error: AxiosError) => {
      toast.error("Failed to bulk label results");
      onError?.(error);
    },
  });

  // Mark complete mutation
  const markComplete = useMutation({
    mutationFn: () =>
      api.searchSessions.markComplete(mlProjectUuid, sessionUuid),
    onSuccess: (data) => {
      toast.success("Search session marked as complete");
      onMarkComplete?.(data);
      queryClient.invalidateQueries({
        queryKey: ["search_session", mlProjectUuid, sessionUuid],
      });
    },
    onError: (error: AxiosError) => {
      toast.error("Failed to mark session complete");
      onError?.(error);
    },
  });

  return {
    // Session data
    session: sessionQuery.data,
    isLoading: sessionQuery.isLoading,
    isError: sessionQuery.isError,
    error: sessionQuery.error,
    refetch: sessionQuery.refetch,

    // Progress
    progress: progressQuery.data,
    progressLoading: progressQuery.isLoading,
    refetchProgress: progressQuery.refetch,

    // Results
    results: results.items,
    resultsTotal: results.total,
    resultsPagination: results.pagination,
    resultFilter,
    resultsLoading: results.query.isLoading,
    refetchResults: results.query.refetch,

    // Mutations
    execute,
    labelResult,
    bulkLabel,
    markComplete,
  } as const;
}
