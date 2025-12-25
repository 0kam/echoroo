"use client";

/**
 * Inference Batch detail page.
 *
 * Displays detailed information about an inference batch,
 * including predictions with review functionality.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  ChevronLeft,
  Play,
  Pause,
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  Filter,
  Check,
  X,
  HelpCircle,
  Music,
  Download,
  ArrowLeft,
  ArrowRight,
  Target,
} from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import ProgressBar from "@/lib/components/ui/ProgressBar";
import Link from "@/lib/components/ui/Link";

import type {
  InferenceBatch,
  InferenceBatchStatus,
  InferencePrediction,
  InferencePredictionReviewStatus,
} from "@/lib/types";

// Status badge colors
const STATUS_COLORS: Record<InferenceBatchStatus, string> = {
  pending: "bg-stone-200 text-stone-700 dark:bg-stone-700 dark:text-stone-300",
  running: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  failed: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  cancelled: "bg-stone-300 text-stone-600 dark:bg-stone-600 dark:text-stone-400",
};

const STATUS_ICONS: Record<InferenceBatchStatus, React.ReactNode> = {
  pending: <Clock className="w-4 h-4" />,
  running: <Loader2 className="w-4 h-4 animate-spin" />,
  completed: <CheckCircle className="w-4 h-4" />,
  failed: <XCircle className="w-4 h-4" />,
  cancelled: <Pause className="w-4 h-4" />,
};

const REVIEW_STATUS_COLORS: Record<InferencePredictionReviewStatus, string> = {
  unreviewed: "bg-stone-100 text-stone-600 dark:bg-stone-700 dark:text-stone-400",
  confirmed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  rejected: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  uncertain: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
};

function StatusBadge({ status }: { status: InferenceBatchStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-full ${STATUS_COLORS[status]}`}
    >
      {STATUS_ICONS[status]}
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function PredictionCard({
  prediction,
  isSelected,
  onClick,
  onReview,
}: {
  prediction: InferencePrediction;
  isSelected: boolean;
  onClick: () => void;
  onReview: (status: InferencePredictionReviewStatus) => void;
}) {
  return (
    <Card
      className={`cursor-pointer transition-all ${
        isSelected
          ? "ring-2 ring-emerald-500 border-emerald-500"
          : "hover:border-emerald-500/50"
      }`}
      onClick={onClick}
    >
      {/* Spectrogram placeholder */}
      <div className="aspect-[2/1] bg-stone-100 dark:bg-stone-800 rounded-lg mb-2 flex items-center justify-center relative">
        <Music className="w-6 h-6 text-stone-400" />
        {/* Confidence badge */}
        <span
          className={`absolute top-2 right-2 px-2 py-0.5 text-xs rounded-full ${
            prediction.predicted_positive
              ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400"
              : "bg-stone-100 dark:bg-stone-700 text-stone-600 dark:text-stone-400"
          }`}
        >
          {(prediction.confidence * 100).toFixed(1)}%
        </span>
        {/* Predicted positive/negative badge */}
        {prediction.predicted_positive && (
          <span className="absolute top-2 left-2 px-1.5 py-0.5 text-xs font-bold rounded bg-emerald-500 text-white">
            +
          </span>
        )}
      </div>

      {/* Review status */}
      <div className="flex items-center justify-between mb-2">
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${REVIEW_STATUS_COLORS[prediction.review_status]}`}
        >
          {prediction.review_status.charAt(0).toUpperCase() + prediction.review_status.slice(1)}
        </span>
      </div>

      {/* Quick review buttons */}
      <div className="flex items-center gap-1">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onReview("confirmed");
          }}
          className={`flex-1 p-1.5 rounded text-xs transition-colors ${
            prediction.review_status === "confirmed"
              ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700"
              : "hover:bg-emerald-50 dark:hover:bg-emerald-900/20 text-stone-500"
          }`}
          title="Confirm"
        >
          <Check className="w-4 h-4 mx-auto" />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onReview("rejected");
          }}
          className={`flex-1 p-1.5 rounded text-xs transition-colors ${
            prediction.review_status === "rejected"
              ? "bg-red-100 dark:bg-red-900/30 text-red-700"
              : "hover:bg-red-50 dark:hover:bg-red-900/20 text-stone-500"
          }`}
          title="Reject"
        >
          <X className="w-4 h-4 mx-auto" />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onReview("uncertain");
          }}
          className={`flex-1 p-1.5 rounded text-xs transition-colors ${
            prediction.review_status === "uncertain"
              ? "bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700"
              : "hover:bg-yellow-50 dark:hover:bg-yellow-900/20 text-stone-500"
          }`}
          title="Uncertain"
        >
          <HelpCircle className="w-4 h-4 mx-auto" />
        </button>
      </div>
    </Card>
  );
}

function ReviewPanel({
  prediction,
  onReview,
  onPrevious,
  onNext,
  hasPrevious,
  hasNext,
  isReviewing,
}: {
  prediction: InferencePrediction;
  onReview: (status: InferencePredictionReviewStatus) => void;
  onPrevious: () => void;
  onNext: () => void;
  hasPrevious: boolean;
  hasNext: boolean;
  isReviewing: boolean;
}) {
  return (
    <Card className="p-4">
      <h4 className="font-medium mb-4">
        Prediction Details
        <span className="ml-2 text-sm font-normal text-stone-500">
          Confidence: {(prediction.confidence * 100).toFixed(1)}%
        </span>
      </h4>

      {/* Spectrogram placeholder */}
      <div className="aspect-[2/1] bg-stone-100 dark:bg-stone-800 rounded-lg mb-4 flex items-center justify-center">
        <Music className="w-12 h-12 text-stone-400" />
      </div>

      {/* Prediction info */}
      <div className="mb-4 space-y-2 text-sm">
        <div className="flex items-center justify-between">
          <span className="text-stone-500">Predicted:</span>
          <span
            className={
              prediction.predicted_positive
                ? "text-emerald-600 font-medium"
                : "text-stone-600"
            }
          >
            {prediction.predicted_positive ? "Positive (Target Present)" : "Negative"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-stone-500">Current Review:</span>
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${REVIEW_STATUS_COLORS[prediction.review_status]}`}
          >
            {prediction.review_status.charAt(0).toUpperCase() +
              prediction.review_status.slice(1)}
          </span>
        </div>
      </div>

      {/* Review buttons */}
      <div className="grid grid-cols-3 gap-2 mb-4">
        <button
          onClick={() => onReview("confirmed")}
          disabled={isReviewing}
          className={`flex flex-col items-center gap-1 p-3 rounded-lg transition-colors ${
            prediction.review_status === "confirmed"
              ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 ring-2 ring-emerald-500"
              : "hover:bg-emerald-50 dark:hover:bg-emerald-900/20 text-stone-600"
          } ${isReviewing ? "opacity-50 cursor-not-allowed" : ""}`}
        >
          <Check className="w-5 h-5" />
          <span className="text-xs font-medium">Confirm</span>
        </button>
        <button
          onClick={() => onReview("rejected")}
          disabled={isReviewing}
          className={`flex flex-col items-center gap-1 p-3 rounded-lg transition-colors ${
            prediction.review_status === "rejected"
              ? "bg-red-100 dark:bg-red-900/30 text-red-700 ring-2 ring-red-500"
              : "hover:bg-red-50 dark:hover:bg-red-900/20 text-stone-600"
          } ${isReviewing ? "opacity-50 cursor-not-allowed" : ""}`}
        >
          <X className="w-5 h-5" />
          <span className="text-xs font-medium">Reject</span>
        </button>
        <button
          onClick={() => onReview("uncertain")}
          disabled={isReviewing}
          className={`flex flex-col items-center gap-1 p-3 rounded-lg transition-colors ${
            prediction.review_status === "uncertain"
              ? "bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 ring-2 ring-yellow-500"
              : "hover:bg-yellow-50 dark:hover:bg-yellow-900/20 text-stone-600"
          } ${isReviewing ? "opacity-50 cursor-not-allowed" : ""}`}
        >
          <HelpCircle className="w-5 h-5" />
          <span className="text-xs font-medium">Uncertain</span>
        </button>
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between pt-4 border-t border-stone-200 dark:border-stone-700">
        <Button
          variant="secondary"
          mode="text"
          onClick={onPrevious}
          disabled={!hasPrevious}
        >
          <ArrowLeft className="w-4 h-4 mr-1" />
          Previous
        </Button>
        <Button
          variant="secondary"
          mode="text"
          onClick={onNext}
          disabled={!hasNext}
        >
          Next
          <ArrowRight className="w-4 h-4 ml-1" />
        </Button>
      </div>

      {/* Keyboard shortcuts */}
      <div className="mt-4 pt-4 border-t border-stone-200 dark:border-stone-700">
        <h5 className="text-xs font-medium text-stone-500 mb-2">Keyboard Shortcuts</h5>
        <div className="grid grid-cols-2 gap-1 text-xs text-stone-500">
          <div className="flex justify-between">
            <span>Confirm</span>
            <kbd className="px-1.5 py-0.5 bg-stone-200 dark:bg-stone-700 rounded">C</kbd>
          </div>
          <div className="flex justify-between">
            <span>Reject</span>
            <kbd className="px-1.5 py-0.5 bg-stone-200 dark:bg-stone-700 rounded">R</kbd>
          </div>
          <div className="flex justify-between">
            <span>Uncertain</span>
            <kbd className="px-1.5 py-0.5 bg-stone-200 dark:bg-stone-700 rounded">U</kbd>
          </div>
          <div className="flex justify-between">
            <span>Navigate</span>
            <span>
              <kbd className="px-1.5 py-0.5 bg-stone-200 dark:bg-stone-700 rounded">
                Arrows
              </kbd>
            </span>
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function InferenceBatchDetailPage() {
  const params = useParams();
  const router = useRouter();
  const mlProjectUuid = params.ml_project_uuid as string;
  const batchUuid = params.batch_uuid as string;
  const queryClient = useQueryClient();

  const [selectedIndex, setSelectedIndex] = useState(0);
  const [reviewFilter, setReviewFilter] = useState<
    InferencePredictionReviewStatus | "all"
  >("all");
  const [page, setPage] = useState(0);
  const pageSize = 24;

  // Fetch batch
  const {
    data: batch,
    isLoading: batchLoading,
    refetch: refetchBatch,
  } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "inference_batch", batchUuid],
    queryFn: () => api.inferenceBatches.get(mlProjectUuid, batchUuid),
    enabled: !!mlProjectUuid && !!batchUuid,
    refetchInterval: (query) => {
      // Refetch more frequently if batch is running
      const batchData = query.state.data;
      return batchData?.status === "running" ? 5000 : false;
    },
  });

  // Fetch predictions
  const {
    data: predictionsData,
    isLoading: predictionsLoading,
    refetch: refetchPredictions,
  } = useQuery({
    queryKey: [
      "ml_project",
      mlProjectUuid,
      "inference_batch",
      batchUuid,
      "predictions",
      reviewFilter,
      page,
    ],
    queryFn: () =>
      api.inferenceBatches.getPredictions(mlProjectUuid, batchUuid, {
        limit: pageSize,
        offset: page * pageSize,
        review_status: reviewFilter === "all" ? undefined : reviewFilter,
      }),
    enabled: !!batch && batch.status === "completed",
  });

  const predictions = predictionsData?.items || [];
  const totalPredictions = predictionsData?.total || 0;
  const numPages = Math.ceil(totalPredictions / pageSize);

  const selectedPrediction = predictions[selectedIndex];

  // Review stats
  const reviewStats = useMemo(() => {
    if (!batch) return { confirmed: 0, rejected: 0, uncertain: 0, unreviewed: 0 };
    // These would ideally come from the batch or a separate stats endpoint
    return {
      confirmed: 0,
      rejected: 0,
      uncertain: 0,
      unreviewed: batch.positive_predictions,
    };
  }, [batch]);

  // Start batch mutation
  const startMutation = useMutation({
    mutationFn: () => api.inferenceBatches.start(mlProjectUuid, batchUuid),
    onSuccess: () => {
      toast.success("Inference started");
      refetchBatch();
    },
    onError: () => {
      toast.error("Failed to start inference");
    },
  });

  // Cancel batch mutation
  const cancelMutation = useMutation({
    mutationFn: () => api.inferenceBatches.cancel(mlProjectUuid, batchUuid),
    onSuccess: () => {
      toast.success("Inference cancelled");
      refetchBatch();
    },
    onError: () => {
      toast.error("Failed to cancel inference");
    },
  });

  // Review prediction mutation
  const reviewMutation = useMutation({
    mutationFn: ({
      predictionUuid,
      status,
    }: {
      predictionUuid: string;
      status: InferencePredictionReviewStatus;
    }) =>
      api.inferenceBatches.reviewPrediction(
        mlProjectUuid,
        batchUuid,
        predictionUuid,
        { review_status: status }
      ),
    onSuccess: () => {
      refetchPredictions();
      // Auto-advance to next
      if (selectedIndex < predictions.length - 1) {
        setSelectedIndex(selectedIndex + 1);
      } else if (page < numPages - 1) {
        setPage(page + 1);
        setSelectedIndex(0);
      }
    },
    onError: () => {
      toast.error("Failed to review prediction");
    },
  });

  // Handle review
  const handleReview = useCallback(
    (predictionUuid: string, status: InferencePredictionReviewStatus) => {
      if (reviewMutation.isPending) return;
      reviewMutation.mutate({ predictionUuid, status });
    },
    [reviewMutation]
  );

  // Navigation handlers
  const handlePrevious = useCallback(() => {
    if (selectedIndex > 0) {
      setSelectedIndex(selectedIndex - 1);
    } else if (page > 0) {
      setPage(page - 1);
      setSelectedIndex(pageSize - 1);
    }
  }, [selectedIndex, page, pageSize]);

  const handleNext = useCallback(() => {
    if (selectedIndex < predictions.length - 1) {
      setSelectedIndex(selectedIndex + 1);
    } else if (page < numPages - 1) {
      setPage(page + 1);
      setSelectedIndex(0);
    }
  }, [selectedIndex, predictions.length, page, numPages]);

  // Keyboard shortcuts
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement
      ) {
        return;
      }

      if (!selectedPrediction) return;

      switch (e.key.toLowerCase()) {
        case "c":
          handleReview(selectedPrediction.uuid, "confirmed");
          break;
        case "r":
          handleReview(selectedPrediction.uuid, "rejected");
          break;
        case "u":
          handleReview(selectedPrediction.uuid, "uncertain");
          break;
        case "arrowleft":
          handlePrevious();
          break;
        case "arrowright":
          handleNext();
          break;
      }
    },
    [selectedPrediction, handleReview, handlePrevious, handleNext]
  );

  // Register keyboard shortcuts
  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  if (batchLoading) {
    return <Loading />;
  }

  if (!batch) {
    return null;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href={`/ml-projects/${mlProjectUuid}/inference`}>
            <Button variant="secondary" mode="text">
              <ChevronLeft className="w-4 h-4 mr-1" />
              Back to Batches
            </Button>
          </Link>
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-semibold text-stone-900 dark:text-stone-100">
                {batch.name}
              </h2>
              <StatusBadge status={batch.status} />
            </div>
            {batch.description && (
              <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
                {batch.description}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {batch.status === "pending" && (
            <Button
              variant="primary"
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending}
            >
              {startMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Play className="w-4 h-4 mr-2" />
              )}
              Start Inference
            </Button>
          )}
          {batch.status === "running" && (
            <Button
              variant="secondary"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
            >
              {cancelMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Pause className="w-4 h-4 mr-2" />
              )}
              Cancel
            </Button>
          )}
          {batch.status === "completed" && (
            <Button variant="secondary">
              <Download className="w-4 h-4 mr-2" />
              Export
            </Button>
          )}
        </div>
      </div>

      {/* Batch Info */}
      <Card className="p-4">
        <div className="flex items-center gap-6 text-sm text-stone-600 dark:text-stone-400">
          <div className="flex items-center gap-2">
            <Target className="w-4 h-4" />
            <span>Model: {batch.custom_model.name}</span>
          </div>
          <div>
            Target: {batch.custom_model.target_tag.key}:{" "}
            {batch.custom_model.target_tag.value}
          </div>
          <div>Threshold: {(batch.confidence_threshold * 100).toFixed(0)}%</div>
        </div>

        {/* Progress */}
        {(batch.status === "running" || batch.status === "completed") && (
          <div className="mt-4">
            <div className="flex items-center justify-between text-sm mb-2">
              <span className="text-stone-500">Progress</span>
              <span className="text-stone-700 dark:text-stone-300">
                {batch.processed_items} / {batch.total_items} (
                {(batch.progress * 100).toFixed(1)}%)
              </span>
            </div>
            <ProgressBar
              total={batch.total_items}
              complete={batch.processed_items}
              className="mb-2"
            />
            <div className="text-sm text-stone-500">
              {batch.positive_predictions} positive predictions detected
            </div>
          </div>
        )}

        {/* Error message */}
        {batch.status === "failed" && batch.error_message && (
          <div className="mt-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
            <p className="text-sm text-red-600 dark:text-red-400">
              {batch.error_message}
            </p>
          </div>
        )}
      </Card>

      {/* Predictions (only for completed batches) */}
      {batch.status === "completed" && (
        <>
          {/* Filter and stats */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Filter className="w-4 h-4 text-stone-400" />
                <span className="text-sm text-stone-600 dark:text-stone-400">
                  Filter:
                </span>
              </div>
              <select
                value={reviewFilter}
                onChange={(e) => {
                  setReviewFilter(
                    e.target.value as InferencePredictionReviewStatus | "all"
                  );
                  setPage(0);
                  setSelectedIndex(0);
                }}
                className="px-3 py-1.5 text-sm border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
              >
                <option value="all">All predictions</option>
                <option value="unreviewed">Unreviewed</option>
                <option value="confirmed">Confirmed</option>
                <option value="rejected">Rejected</option>
                <option value="uncertain">Uncertain</option>
              </select>
              <span className="text-sm text-stone-500">
                {totalPredictions} predictions
              </span>
            </div>
          </div>

          {/* Main content */}
          <div className="grid grid-cols-12 gap-6">
            {/* Predictions grid */}
            <div className="col-span-8">
              {predictionsLoading ? (
                <Loading />
              ) : predictions.length === 0 ? (
                <Empty>
                  <Music className="w-12 h-12 mb-4 text-stone-400" />
                  <p className="text-lg font-medium">No predictions found</p>
                  <p className="text-sm text-stone-500 mt-1">
                    {reviewFilter !== "all"
                      ? "Try changing the filter to see more predictions"
                      : "No predictions were generated for this batch"}
                  </p>
                </Empty>
              ) : (
                <>
                  <div className="grid grid-cols-4 gap-3">
                    {predictions.map((prediction, index) => (
                      <PredictionCard
                        key={prediction.uuid}
                        prediction={prediction}
                        isSelected={index === selectedIndex}
                        onClick={() => setSelectedIndex(index)}
                        onReview={(status) =>
                          handleReview(prediction.uuid, status)
                        }
                      />
                    ))}
                  </div>

                  {/* Pagination */}
                  {numPages > 1 && (
                    <div className="flex items-center justify-between mt-4">
                      <Button
                        variant="secondary"
                        disabled={page === 0}
                        onClick={() => {
                          setPage(page - 1);
                          setSelectedIndex(0);
                        }}
                      >
                        <ArrowLeft className="w-4 h-4 mr-1" />
                        Previous
                      </Button>
                      <span className="text-sm text-stone-500">
                        Page {page + 1} of {numPages}
                      </span>
                      <Button
                        variant="secondary"
                        disabled={page >= numPages - 1}
                        onClick={() => {
                          setPage(page + 1);
                          setSelectedIndex(0);
                        }}
                      >
                        Next
                        <ArrowRight className="w-4 h-4 ml-1" />
                      </Button>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Review panel */}
            <div className="col-span-4">
              {selectedPrediction && (
                <ReviewPanel
                  prediction={selectedPrediction}
                  onReview={(status) =>
                    handleReview(selectedPrediction.uuid, status)
                  }
                  onPrevious={handlePrevious}
                  onNext={handleNext}
                  hasPrevious={selectedIndex > 0 || page > 0}
                  hasNext={
                    selectedIndex < predictions.length - 1 || page < numPages - 1
                  }
                  isReviewing={reviewMutation.isPending}
                />
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
