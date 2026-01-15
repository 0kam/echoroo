"use client";

/**
 * Inference Batches page.
 *
 * Displays a list of inference batches with their status and progress.
 * Allows creating new batches and viewing/reviewing predictions.
 */
import { useCallback, useContext, useState, useEffect } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
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
  Target,
  Eye,
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

function BatchCard({
  batch,
  mlProjectUuid,
  onStart,
  onCancel,
  onDelete,
}: {
  batch: InferenceBatch;
  mlProjectUuid: string;
  onStart: () => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  const router = useRouter();

  return (
    <Card>
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
            {batch.name || `Inference Batch ${batch.uuid.slice(0, 8)}`}
          </h3>
          {batch.description && (
            <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
              {batch.description}
            </p>
          )}
        </div>
        <StatusBadge status={batch.status} />
      </div>

      {/* Info */}
      <div className="mt-3 flex items-center gap-4 text-sm text-stone-600 dark:text-stone-400">
        <div className="flex items-center gap-1">
          <Target className="w-4 h-4" />
          <span>Model: {batch.custom_model?.name || "Unknown"}</span>
        </div>
        <div>
          Threshold: {(batch.confidence_threshold * 100).toFixed(0)}%
        </div>
      </div>

      {/* Progress (for running or completed) */}
      {(batch.status === "running" || batch.status === "completed") && batch.total_clips > 0 && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-stone-500">Progress</span>
            <span className="text-stone-700 dark:text-stone-300">
              {batch.processed_clips} / {batch.total_clips} (
              {batch.total_clips > 0
                ? ((batch.processed_clips / batch.total_clips) * 100).toFixed(1)
                : "0.0"}%)
            </span>
          </div>
          <ProgressBar
            total={batch.total_clips}
            segments={[
              {
                count: batch.processed_clips,
                color: "#10b981",
                label: "Processed",
              },
              {
                count: batch.total_clips - batch.processed_clips,
                color: "#d1d5db",
                label: "Pending",
              },
            ]}
            className="mb-2"
          />
          <div className="text-sm text-stone-500">
            {batch.total_predictions} total predictions
          </div>
        </div>
      )}

      {/* Summary Statistics (for completed batches only) */}
      {batch.status === "completed" && batch.total_predictions > 0 && (
        <div className="mt-3 pt-3 border-t border-stone-200 dark:border-stone-700">
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div>
              <div className="text-stone-500 dark:text-stone-400">Positive</div>
              <div className="font-medium text-emerald-600 dark:text-emerald-400">
                {batch.positive_predictions_count} ({((batch.positive_predictions_count / batch.total_predictions) * 100).toFixed(1)}%)
              </div>
            </div>
            <div>
              <div className="text-stone-500 dark:text-stone-400">Negative</div>
              <div className="font-medium">
                {batch.negative_predictions_count} ({((batch.negative_predictions_count / batch.total_predictions) * 100).toFixed(1)}%)
              </div>
            </div>
            <div>
              <div className="text-stone-500 dark:text-stone-400">Avg Conf.</div>
              <div className="font-medium">
                {batch.average_confidence ? (batch.average_confidence * 100).toFixed(1) : '-'}%
              </div>
            </div>
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
          {batch.status === "completed" && (
            <Button
              variant="secondary"
              onClick={() => router.push(`/ml-projects/${mlProjectUuid}/inference/${batch.uuid}`)}
            >
              <Eye className="w-4 h-4 mr-1" />
              View Details
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}

function CreateBatchDialog({
  isOpen,
  onClose,
  mlProjectUuid,
  onSuccess,
  preselectedModelUuid,
}: {
  isOpen: boolean;
  onClose: () => void;
  mlProjectUuid: string;
  onSuccess: () => void;
  preselectedModelUuid?: string;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [customModelId, setCustomModelId] = useState<string>("");
  const [confidenceThreshold, setConfidenceThreshold] = useState("0.5");
  const [batchSize, setBatchSize] = useState("100");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch trained and deployed models
  const { data: modelsData } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "custom_models"],
    queryFn: () => api.customModels.getMany(mlProjectUuid, { limit: 100 }),
  });
  // Filter to only show trained or deployed models (ready for inference)
  const models = (modelsData?.items || []).filter(
    (model) => model.status === "trained" || model.status === "deployed"
  );

  // Set preselected model when dialog opens
  useEffect(() => {
    if (isOpen && preselectedModelUuid) {
      setCustomModelId(preselectedModelUuid);
    }
  }, [isOpen, preselectedModelUuid]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !customModelId) return;

    setIsSubmitting(true);
    try {
      await api.inferenceBatches.create(mlProjectUuid, {
        name,
        custom_model_uuid: customModelId,
        confidence_threshold: parseFloat(confidenceThreshold),
        include_all_clips: true,
        description: description || undefined,
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
                  {model.name} ({model.tag.key}: {model.tag.value})
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
  const searchParams = useSearchParams();
  const mlProjectUuid = params.ml_project_uuid as string;
  const mlProject = useContext(MLProjectContext);
  const queryClient = useQueryClient();
  const preselectedModelUuid = searchParams.get("model");

  const [showCreateDialog, setShowCreateDialog] = useState(false);

  // Auto-open create dialog when model is preselected via URL parameter
  useEffect(() => {
    if (preselectedModelUuid) {
      setShowCreateDialog(true);
    }
  }, [preselectedModelUuid]);

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
        preselectedModelUuid={preselectedModelUuid || undefined}
      />
    </div>
  );
}
