import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import toast from "react-hot-toast";

import api from "@/app/api";

import type { CustomModel, TrainingProgress } from "@/lib/types";

/**
 * Custom hook for managing a single custom model.
 *
 * This hook encapsulates the logic for querying a custom model,
 * starting training, getting training status with optional polling,
 * and deploying/archiving the model.
 */
export default function useCustomModel({
  mlProjectUuid,
  modelUuid,
  enabled = true,
  statusPollingInterval,
  onStartTraining,
  onDeploy,
  onArchive,
  onError,
}: {
  mlProjectUuid: string;
  modelUuid: string;
  enabled?: boolean;
  statusPollingInterval?: number;
  onStartTraining?: (model: CustomModel) => void;
  onDeploy?: (model: CustomModel) => void;
  onArchive?: (model: CustomModel) => void;
  onError?: (error: AxiosError) => void;
}) {
  const queryClient = useQueryClient();

  // Main model query
  const modelQuery = useQuery<CustomModel, AxiosError>({
    queryKey: ["custom_model", mlProjectUuid, modelUuid],
    queryFn: () => api.customModels.get(mlProjectUuid, modelUuid),
    enabled: enabled && !!mlProjectUuid && !!modelUuid,
  });

  // Training status query with optional polling
  const statusQuery = useQuery<TrainingProgress, AxiosError>({
    queryKey: ["custom_model", mlProjectUuid, modelUuid, "status"],
    queryFn: () => api.customModels.getTrainingStatus(mlProjectUuid, modelUuid),
    enabled: enabled && !!mlProjectUuid && !!modelUuid,
    refetchInterval: statusPollingInterval,
  });

  // Start training mutation
  const startTraining = useMutation({
    mutationFn: () => api.customModels.startTraining(mlProjectUuid, modelUuid),
    onSuccess: (data) => {
      toast.success("Training started");
      onStartTraining?.(data);
      queryClient.invalidateQueries({
        queryKey: ["custom_model", mlProjectUuid, modelUuid],
      });
    },
    onError: (error: AxiosError) => {
      toast.error("Failed to start training");
      onError?.(error);
    },
  });

  // Deploy mutation
  const deploy = useMutation({
    mutationFn: () => api.customModels.deploy(mlProjectUuid, modelUuid),
    onSuccess: (data) => {
      toast.success("Model deployed");
      onDeploy?.(data);
      queryClient.invalidateQueries({
        queryKey: ["custom_model", mlProjectUuid, modelUuid],
      });
    },
    onError: (error: AxiosError) => {
      toast.error("Failed to deploy model");
      onError?.(error);
    },
  });

  // Archive mutation
  const archive = useMutation({
    mutationFn: () => api.customModels.archive(mlProjectUuid, modelUuid),
    onSuccess: (data) => {
      toast.success("Model archived");
      onArchive?.(data);
      queryClient.invalidateQueries({
        queryKey: ["custom_model", mlProjectUuid, modelUuid],
      });
    },
    onError: (error: AxiosError) => {
      toast.error("Failed to archive model");
      onError?.(error);
    },
  });

  return {
    // Model data
    model: modelQuery.data,
    isLoading: modelQuery.isLoading,
    isError: modelQuery.isError,
    error: modelQuery.error,
    refetch: modelQuery.refetch,

    // Training status
    status: statusQuery.data,
    statusLoading: statusQuery.isLoading,
    refetchStatus: statusQuery.refetch,

    // Mutations
    startTraining,
    deploy,
    archive,
  } as const;
}
