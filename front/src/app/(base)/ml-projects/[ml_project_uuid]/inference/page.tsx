"use client";

/**
 * Inference Batches page.
 *
 * Displays a list of inference batches with their status and progress.
 * Allows creating new batches and viewing/reviewing predictions.
 */
import { useCallback, useContext, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  Plus,
  Play,
  Pause,
  CheckCircle,
  XCircle,
  Clock,
  Trash2,
  Loader2,
  Eye,
  ChevronRight,
  ChevronDown,
  Target,
  Filter,
  Check,
  X,
  HelpCircle,
  Music,
} from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import ProgressBar from "@/lib/components/ui/ProgressBar";
import { DialogOverlay } from "@/lib/components/ui/Dialog";

import type {
  InferenceBatch,
  InferenceBatchCreate,
  InferenceBatchStatus,
  InferencePrediction,
  InferencePredictionReviewStatus,
  CustomModel,
} from "@/lib/types";

import MLProjectContext from "../context";

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
  onReview,
}: {
  prediction: InferencePrediction;
  onReview: (status: InferencePredictionReviewStatus) => void;
}) {
  return (
    <Card className="p-3">
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
      </div>

      {/* Review status */}
      <div className="flex items-center justify-between mb-2">
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${REVIEW_STATUS_COLORS[prediction.review_status]}`}
        >
          {prediction.review_status.charAt(0).toUpperCase() + prediction.review_status.slice(1)}
        </span>
        {prediction.predicted_positive && (
          <span className="text-xs text-emerald-600 dark:text-emerald-400">Positive</span>
        )}
      </div>

      {/* Review buttons */}
      <div className="flex items-center gap-1">
        <button
          onClick={() => onReview("confirmed")}
          className={`flex-1 p-1.5 rounded text-xs ${
            prediction.review_status === "confirmed"
              ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700"
              : "hover:bg-emerald-50 dark:hover:bg-emerald-900/20 text-stone-500"
          }`}
          title="Confirm"
        >
          <Check className="w-4 h-4 mx-auto" />
        </button>
        <button
          onClick={() => onReview("rejected")}
          className={`flex-1 p-1.5 rounded text-xs ${
            prediction.review_status === "rejected"
              ? "bg-red-100 dark:bg-red-900/30 text-red-700"
              : "hover:bg-red-50 dark:hover:bg-red-900/20 text-stone-500"
          }`}
          title="Reject"
        >
          <X className="w-4 h-4 mx-auto" />
        </button>
        <button
          onClick={() => onReview("uncertain")}
          className={`flex-1 p-1.5 rounded text-xs ${
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

function BatchCard({
  batch,
  mlProjectUuid,
  onStart,
  onCancel,
  onDelete,
  isExpanded,
  onToggleExpand,
}: {
  batch: InferenceBatch;
  mlProjectUuid: string;
  onStart: () => void;
  onCancel: () => void;
  onDelete: () => void;
  isExpanded: boolean;
  onToggleExpand: () => void;
}) {
  const queryClient = useQueryClient();
  const [reviewFilter, setReviewFilter] = useState<InferencePredictionReviewStatus | "all">("all");
  const [page, setPage] = useState(0);
  const pageSize = 12;

  // Fetch predictions when expanded
  const { data: predictionsData, refetch: refetchPredictions } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "inference_batch", batch.uuid, "predictions", reviewFilter, page],
    queryFn: () =>
      api.inferenceBatches.getPredictions(mlProjectUuid, batch.uuid, {
        limit: pageSize,
        offset: page * pageSize,
        review_status: reviewFilter === "all" ? undefined : reviewFilter,
      }),
    enabled: isExpanded && batch.status === "completed",
  });

  const predictions = predictionsData?.items || [];
  const totalPredictions = predictionsData?.total || 0;
  const numPages = Math.ceil(totalPredictions / pageSize);

  // Review mutation
  const reviewMutation = useMutation({
    mutationFn: ({
      predictionUuid,
      status,
    }: {
      predictionUuid: string;
      status: InferencePredictionReviewStatus;
    }) =>
      api.inferenceBatches.reviewPrediction(mlProjectUuid, batch.uuid, predictionUuid, {
        review_status: status,
      }),
    onSuccess: () => {
      refetchPredictions();
    },
    onError: () => {
      toast.error("Failed to review prediction");
    },
  });

  return (
    <Card>
      {/* Header */}
      <div
        className="flex items-start justify-between cursor-pointer"
        onClick={onToggleExpand}
      >
        <div className="flex items-center gap-2">
          {batch.status === "completed" && (
            <button className="text-stone-400 hover:text-stone-600">
              {isExpanded ? (
                <ChevronDown className="w-5 h-5" />
              ) : (
                <ChevronRight className="w-5 h-5" />
              )}
            </button>
          )}
          <div>
            <h3 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
              {batch.name}
            </h3>
            {batch.description && (
              <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
                {batch.description}
              </p>
            )}
          </div>
        </div>
        <StatusBadge status={batch.status} />
      </div>

      {/* Info */}
      <div className="mt-3 flex items-center gap-4 text-sm text-stone-600 dark:text-stone-400">
        <div className="flex items-center gap-1">
          <Target className="w-4 h-4" />
          <span>Model: {batch.custom_model.name}</span>
        </div>
        <div>
          Threshold: {(batch.confidence_threshold * 100).toFixed(0)}%
        </div>
      </div>

      {/* Progress (for running or completed) */}
      {(batch.status === "running" || batch.status === "completed") && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-stone-500">Progress</span>
            <span className="text-stone-700 dark:text-stone-300">
              {batch.processed_items} / {batch.total_items} ({(batch.progress * 100).toFixed(1)}%)
            </span>
          </div>
          <ProgressBar
            total={batch.total_items}
            complete={batch.processed_items}
            className="mb-2"
          />
          <div className="text-sm text-stone-500">
            {batch.positive_predictions} positive predictions
          </div>
        </div>
      )}

      {/* Error message */}
      {batch.status === "failed" && batch.error_message && (
        <div className="mt-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-sm text-red-600 dark:text-red-400">{batch.error_message}</p>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between mt-4 pt-3 border-t border-stone-200 dark:border-stone-700">
        <Button variant="danger" mode="text" onClick={onDelete}>
          <Trash2 className="w-4 h-4" />
        </Button>
        <div className="flex items-center gap-2">
          {batch.status === "pending" && (
            <Button variant="primary" onClick={onStart}>
              <Play className="w-4 h-4 mr-1" />
              Start
            </Button>
          )}
          {batch.status === "running" && (
            <Button variant="secondary" onClick={onCancel}>
              <Pause className="w-4 h-4 mr-1" />
              Cancel
            </Button>
          )}
        </div>
      </div>

      {/* Predictions (expanded view) */}
      {isExpanded && batch.status === "completed" && (
        <div className="mt-4 pt-4 border-t border-stone-200 dark:border-stone-700">
          {/* Filter */}
          <div className="flex items-center gap-4 mb-4">
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-stone-400" />
              <span className="text-sm text-stone-600 dark:text-stone-400">Filter:</span>
            </div>
            <select
              value={reviewFilter}
              onChange={(e) => {
                setReviewFilter(e.target.value as InferencePredictionReviewStatus | "all");
                setPage(0);
              }}
              className="px-3 py-1.5 text-sm border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            >
              <option value="all">All</option>
              <option value="unreviewed">Unreviewed</option>
              <option value="confirmed">Confirmed</option>
              <option value="rejected">Rejected</option>
              <option value="uncertain">Uncertain</option>
            </select>
            <span className="text-sm text-stone-500">
              {totalPredictions} predictions
            </span>
          </div>

          {/* Predictions grid */}
          {predictions.length === 0 ? (
            <div className="text-center py-8 text-stone-500">
              No predictions found
            </div>
          ) : (
            <>
              <div className="grid grid-cols-4 gap-3">
                {predictions.map((prediction) => (
                  <PredictionCard
                    key={prediction.uuid}
                    prediction={prediction}
                    onReview={(status) =>
                      reviewMutation.mutate({ predictionUuid: prediction.uuid, status })
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
                    onClick={() => setPage(page - 1)}
                  >
                    Previous
                  </Button>
                  <span className="text-sm text-stone-500">
                    Page {page + 1} of {numPages}
                  </span>
                  <Button
                    variant="secondary"
                    disabled={page >= numPages - 1}
                    onClick={() => setPage(page + 1)}
                  >
                    Next
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </Card>
  );
}

function CreateBatchDialog({
  isOpen,
  onClose,
  mlProjectUuid,
  onSuccess,
}: {
  isOpen: boolean;
  onClose: () => void;
  mlProjectUuid: string;
  onSuccess: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [customModelId, setCustomModelId] = useState<string>("");
  const [confidenceThreshold, setConfidenceThreshold] = useState("0.5");
  const [batchSize, setBatchSize] = useState("100");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch deployed models
  const { data: modelsData } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "custom_models", "deployed"],
    queryFn: () => api.customModels.getMany(mlProjectUuid, { status: "deployed", limit: 100 }),
  });
  const models = modelsData?.items || [];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !customModelId) return;

    setIsSubmitting(true);
    try {
      await api.inferenceBatches.create(mlProjectUuid, {
        name,
        description: description || undefined,
        custom_model_id: customModelId,
        confidence_threshold: parseFloat(confidenceThreshold),
        batch_size: parseInt(batchSize),
      });
      toast.success("Inference batch created");
      setName("");
      setDescription("");
      setCustomModelId("");
      setConfidenceThreshold("0.5");
      setBatchSize("100");
      onSuccess();
      onClose();
    } catch (error) {
      toast.error("Failed to create inference batch");
      console.error(error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <DialogOverlay title="Create Inference Batch" isOpen={isOpen} onClose={onClose}>
      <form onSubmit={handleSubmit} className="w-[400px] space-y-4">
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Batch Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            placeholder="e.g., Full dataset inference"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Description (optional)
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            placeholder="Describe this inference batch..."
            rows={2}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Model
          </label>
          {models.length === 0 ? (
            <p className="text-sm text-stone-500">
              No deployed models available. Deploy a trained model first.
            </p>
          ) : (
            <select
              value={customModelId}
              onChange={(e) => setCustomModelId(e.target.value)}
              className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
              required
            >
              <option value="">Select a model</option>
              {models.map((model) => (
                <option key={model.uuid} value={model.uuid}>
                  {model.name} ({model.target_tag.key}: {model.target_tag.value})
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
              Confidence Threshold
            </label>
            <input
              type="number"
              step="0.01"
              min="0"
              max="1"
              value={confidenceThreshold}
              onChange={(e) => setConfidenceThreshold(e.target.value)}
              className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
              Batch Size
            </label>
            <input
              type="number"
              min="1"
              value={batchSize}
              onChange={(e) => setBatchSize(e.target.value)}
              className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={!name || !customModelId || isSubmitting}
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Creating...
              </>
            ) : (
              "Create Batch"
            )}
          </Button>
        </div>
      </form>
    </DialogOverlay>
  );
}

export default function InferencePage() {
  const params = useParams();
  const mlProjectUuid = params.ml_project_uuid as string;
  const mlProject = useContext(MLProjectContext);
  const queryClient = useQueryClient();

  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [expandedBatchId, setExpandedBatchId] = useState<string | null>(null);

  // Fetch batches
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "inference_batches"],
    queryFn: () => api.inferenceBatches.getMany(mlProjectUuid, { limit: 100 }),
    enabled: !!mlProjectUuid,
    refetchInterval: (query) => {
      // Refetch more frequently if any batch is running
      const batches = query.state.data?.items || [];
      const hasRunning = batches.some((b) => b.status === "running");
      return hasRunning ? 5000 : false;
    },
  });

  const batches = data?.items || [];

  // Mutations
  const startMutation = useMutation({
    mutationFn: (batchUuid: string) =>
      api.inferenceBatches.start(mlProjectUuid, batchUuid),
    onSuccess: () => {
      toast.success("Inference started");
      refetch();
    },
    onError: () => {
      toast.error("Failed to start inference");
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (batchUuid: string) =>
      api.inferenceBatches.cancel(mlProjectUuid, batchUuid),
    onSuccess: () => {
      toast.success("Inference cancelled");
      refetch();
    },
    onError: () => {
      toast.error("Failed to cancel inference");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (batchUuid: string) =>
      api.inferenceBatches.delete(mlProjectUuid, batchUuid),
    onSuccess: () => {
      toast.success("Batch deleted");
      refetch();
      queryClient.invalidateQueries({ queryKey: ["ml_project", mlProjectUuid] });
    },
    onError: () => {
      toast.error("Failed to delete batch");
    },
  });

  const handleDelete = useCallback(
    (batchUuid: string) => {
      if (confirm("Are you sure you want to delete this inference batch?")) {
        deleteMutation.mutate(batchUuid);
      }
    },
    [deleteMutation]
  );

  const handleSuccess = useCallback(() => {
    refetch();
    queryClient.invalidateQueries({ queryKey: ["ml_project", mlProjectUuid] });
  }, [refetch, queryClient, mlProjectUuid]);

  if (isLoading) {
    return <Loading />;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-stone-900 dark:text-stone-100">
            Inference
          </h2>
          <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
            Run trained models on new data to detect sounds
          </p>
        </div>
        <Button variant="primary" onClick={() => setShowCreateDialog(true)}>
          <Plus className="w-4 h-4 mr-2" />
          New Inference Batch
        </Button>
      </div>

      {/* Batches List */}
      {batches.length === 0 ? (
        <Empty>
          <Play className="w-12 h-12 mb-4 text-stone-400" />
          <p className="text-lg font-medium">No inference batches</p>
          <p className="text-sm text-stone-500 mt-1">
            Create an inference batch to run your trained models on new data
          </p>
          <Button
            variant="primary"
            className="mt-4"
            onClick={() => setShowCreateDialog(true)}
          >
            <Plus className="w-4 h-4 mr-2" />
            Create Batch
          </Button>
        </Empty>
      ) : (
        <div className="space-y-4">
          {batches.map((batch) => (
            <BatchCard
              key={batch.uuid}
              batch={batch}
              mlProjectUuid={mlProjectUuid}
              onStart={() => startMutation.mutate(batch.uuid)}
              onCancel={() => cancelMutation.mutate(batch.uuid)}
              onDelete={() => handleDelete(batch.uuid)}
              isExpanded={expandedBatchId === batch.uuid}
              onToggleExpand={() =>
                setExpandedBatchId(
                  expandedBatchId === batch.uuid ? null : batch.uuid
                )
              }
            />
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <CreateBatchDialog
        isOpen={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        mlProjectUuid={mlProjectUuid}
        onSuccess={handleSuccess}
      />
    </div>
  );
}
