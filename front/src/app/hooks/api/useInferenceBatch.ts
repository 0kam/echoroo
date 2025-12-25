import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import toast from "react-hot-toast";

import api from "@/app/api";

import useFilter from "@/lib/hooks/utils/useFilter";
import usePagedQuery from "@/lib/hooks/utils/usePagedQuery";

import type {
  InferenceBatch,
  InferenceProgress,
  InferencePrediction,
  InferencePredictionReview,
  InferencePredictionReviewStatus,
} from "@/lib/types";
import type { InferencePredictionFilter } from "@/lib/api/inference_batches";

const emptyPredictionFilter: InferencePredictionFilter = {};
const _fixed: (keyof InferencePredictionFilter)[] = [];

/**
 * Custom hook for managing a single inference batch.
 *
 * This hook encapsulates the logic for querying an inference batch,
 * starting/canceling inference, getting progress with optional polling,
 * managing predictions with pagination, and reviewing predictions.
 */
export default function useInferenceBatch({
  mlProjectUuid,
  batchUuid,
  enabled = true,
  predictionPageSize = 20,
  predictionFilter: initialPredictionFilter = emptyPredictionFilter,
  predictionFilterFixed = _fixed,
  progressPollingInterval,
  onStart,
  onCancel,
  onReviewPrediction,
  onBulkReview,
  onError,
}: {
  mlProjectUuid: string;
  batchUuid: string;
  enabled?: boolean;
  predictionPageSize?: number;
  predictionFilter?: InferencePredictionFilter;
  predictionFilterFixed?: (keyof InferencePredictionFilter)[];
  progressPollingInterval?: number;
  onStart?: (batch: InferenceBatch) => void;
  onCancel?: (batch: InferenceBatch) => void;
  onReviewPrediction?: (prediction: InferencePrediction) => void;
  onBulkReview?: (count: number) => void;
  onError?: (error: AxiosError) => void;
}) {
  const queryClient = useQueryClient();

  // Main batch query
  const batchQuery = useQuery<InferenceBatch, AxiosError>({
    queryKey: ["inference_batch", mlProjectUuid, batchUuid],
    queryFn: () => api.inferenceBatches.get(mlProjectUuid, batchUuid),
    enabled: enabled && !!mlProjectUuid && !!batchUuid,
  });

  // Progress query with optional polling
  const progressQuery = useQuery<InferenceProgress, AxiosError>({
    queryKey: ["inference_batch", mlProjectUuid, batchUuid, "progress"],
    queryFn: () => api.inferenceBatches.getProgress(mlProjectUuid, batchUuid),
    enabled: enabled && !!mlProjectUuid && !!batchUuid,
    refetchInterval: progressPollingInterval,
  });

  // Prediction filter
  const predictionFilter = useFilter<InferencePredictionFilter>({
    defaults: initialPredictionFilter,
    fixed: predictionFilterFixed,
  });

  // Predictions with pagination
  const predictions = usePagedQuery({
    name: `inference_batch_${batchUuid}_predictions`,
    queryFn: (params) =>
      api.inferenceBatches.getPredictions(mlProjectUuid, batchUuid, params),
    pageSize: predictionPageSize,
    filter: predictionFilter.filter,
    enabled: enabled && !!mlProjectUuid && !!batchUuid,
  });

  // Start inference mutation
  const start = useMutation({
    mutationFn: () => api.inferenceBatches.start(mlProjectUuid, batchUuid),
    onSuccess: (data) => {
      toast.success("Inference started");
      onStart?.(data);
      queryClient.invalidateQueries({
        queryKey: ["inference_batch", mlProjectUuid, batchUuid],
      });
    },
    onError: (error: AxiosError) => {
      toast.error("Failed to start inference");
      onError?.(error);
    },
  });

  // Cancel inference mutation
  const cancel = useMutation({
    mutationFn: () => api.inferenceBatches.cancel(mlProjectUuid, batchUuid),
    onSuccess: (data) => {
      toast.success("Inference cancelled");
      onCancel?.(data);
      queryClient.invalidateQueries({
        queryKey: ["inference_batch", mlProjectUuid, batchUuid],
      });
    },
    onError: (error: AxiosError) => {
      toast.error("Failed to cancel inference");
      onError?.(error);
    },
  });

  // Review prediction mutation
  const reviewPrediction = useMutation({
    mutationFn: ({
      predictionUuid,
      data,
    }: {
      predictionUuid: string;
      data: InferencePredictionReview;
    }) =>
      api.inferenceBatches.reviewPrediction(
        mlProjectUuid,
        batchUuid,
        predictionUuid,
        data,
      ),
    onSuccess: (data) => {
      onReviewPrediction?.(data);
      predictions.query.refetch();
    },
    onError: (error: AxiosError) => {
      toast.error("Failed to review prediction");
      onError?.(error);
    },
  });

  // Bulk review mutation
  const bulkReview = useMutation({
    mutationFn: (data: {
      prediction_uuids: string[];
      review_status: InferencePredictionReviewStatus;
    }) => api.inferenceBatches.bulkReview(mlProjectUuid, batchUuid, data),
    onSuccess: (data) => {
      toast.success(`Reviewed ${data.updated_count} predictions`);
      onBulkReview?.(data.updated_count);
      predictions.query.refetch();
    },
    onError: (error: AxiosError) => {
      toast.error("Failed to bulk review predictions");
      onError?.(error);
    },
  });

  return {
    // Batch data
    batch: batchQuery.data,
    isLoading: batchQuery.isLoading,
    isError: batchQuery.isError,
    error: batchQuery.error,
    refetch: batchQuery.refetch,

    // Progress
    progress: progressQuery.data,
    progressLoading: progressQuery.isLoading,
    refetchProgress: progressQuery.refetch,

    // Predictions
    predictions: predictions.items,
    predictionsTotal: predictions.total,
    predictionsPagination: predictions.pagination,
    predictionFilter,
    predictionsLoading: predictions.query.isLoading,
    refetchPredictions: predictions.query.refetch,

    // Mutations
    start,
    cancel,
    reviewPrediction,
    bulkReview,
  } as const;
}
