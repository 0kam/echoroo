"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";

import api from "@/app/api";

import type { MLProjectDatasetScopeCreate } from "@/lib/types";

/**
 * Query key factory for ML Project Dataset Scopes.
 */
export const mlProjectDatasetScopesKeys = {
  all: ["ml_project_dataset_scopes"] as const,
  list: (mlProjectUuid: string) =>
    [...mlProjectDatasetScopesKeys.all, "list", mlProjectUuid] as const,
};

/**
 * Hook to fetch dataset scopes for an ML project.
 *
 * @param mlProjectUuid - The UUID of the ML project
 * @returns Query result with dataset scopes
 */
export function useMLProjectDatasetScopes(mlProjectUuid: string) {
  return useQuery({
    queryKey: mlProjectDatasetScopesKeys.list(mlProjectUuid),
    queryFn: () => api.mlProjects.datasetScopes.list(mlProjectUuid),
    enabled: !!mlProjectUuid,
  });
}

/**
 * Hook to add a dataset scope to an ML project.
 *
 * @param mlProjectUuid - The UUID of the ML project
 * @returns Mutation for adding a dataset scope
 */
export function useAddMLProjectDatasetScope(mlProjectUuid: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: MLProjectDatasetScopeCreate) =>
      api.mlProjects.datasetScopes.add(mlProjectUuid, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: mlProjectDatasetScopesKeys.list(mlProjectUuid),
      });
      toast.success("Dataset scope added successfully");
    },
    onError: (error) => {
      console.error("Failed to add dataset scope:", error);
      toast.error("Failed to add dataset scope");
    },
  });
}

/**
 * Hook to remove a dataset scope from an ML project.
 *
 * @param mlProjectUuid - The UUID of the ML project
 * @returns Mutation for removing a dataset scope
 */
export function useRemoveMLProjectDatasetScope(mlProjectUuid: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (scopeUuid: string) =>
      api.mlProjects.datasetScopes.remove(mlProjectUuid, scopeUuid),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: mlProjectDatasetScopesKeys.list(mlProjectUuid),
      });
      toast.success("Dataset scope removed successfully");
    },
    onError: (error) => {
      console.error("Failed to remove dataset scope:", error);
      toast.error("Failed to remove dataset scope");
    },
  });
}
