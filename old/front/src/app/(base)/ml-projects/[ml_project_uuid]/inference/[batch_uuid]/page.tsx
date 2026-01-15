"use client";

/**
 * Inference Batch detail page.
 *
 * Displays summary statistics and results for an inference batch.
 */
import { useState, useMemo, useCallback } from "react";
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
  Download,
  Target,
} from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Loading from "@/lib/components/ui/Loading";
import ProgressBar from "@/lib/components/ui/ProgressBar";
import Link from "@/lib/components/ui/Link";
import { ExportInferenceBatchDialog } from "@/app/components/ml_projects";
import DetectionVisualizationPanel from "@/app/components/detection_visualization/DetectionVisualizationPanel";

import type {
  InferenceBatch,
  InferenceBatchStatus,
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

// ============================================================================
// Statistic Row Component
// ============================================================================

function StatRow({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color?: "emerald" | "stone" | "default";
}) {
  const colorStyles = {
    emerald: "text-emerald-600 dark:text-emerald-400",
    stone: "text-stone-500 dark:text-stone-400",
    default: "text-stone-700 dark:text-stone-300",
  };

  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm text-stone-600 dark:text-stone-400">
        {label}
      </span>
      <span
        className={`text-sm font-medium ${colorStyles[color ?? "default"]}`}
      >
        {value}
      </span>
    </div>
  );
}

export default function InferenceBatchDetailPage() {
  const params = useParams();
  const router = useRouter();
  const mlProjectUuid = params.ml_project_uuid as string;
  const batchUuid = params.batch_uuid as string;
  const queryClient = useQueryClient();

  // Export dialog state
  const [isExportDialogOpen, setIsExportDialogOpen] = useState(false);

  // Handle export success - navigate to the created annotation project
  const handleExportSuccess = useCallback((annotationProjectUuid: string) => {
    // Navigate to the annotation project
    router.push(`/annotation-projects/${annotationProjectUuid}`);
  }, [router]);

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

  // Calculate statistics
  const stats = useMemo(() => {
    if (!batch) {
      return {
        totalPredictions: 0,
        positiveCount: 0,
        negativeCount: 0,
        positiveRate: 0,
        negativeRate: 0,
        averageConfidence: 0,
      };
    }

    const totalPredictions = batch.total_predictions;
    const positiveCount = batch.positive_predictions_count;
    const negativeCount = batch.negative_predictions_count;
    const positiveRate = totalPredictions > 0
      ? (positiveCount / totalPredictions) * 100
      : 0;
    const negativeRate = totalPredictions > 0
      ? (negativeCount / totalPredictions) * 100
      : 0;

    // Average confidence comes as 0-1 from backend, convert to percentage
    const averageConfidence = batch.average_confidence !== null
      ? batch.average_confidence * 100
      : 0;

    return {
      totalPredictions,
      positiveCount,
      negativeCount,
      positiveRate,
      negativeRate,
      averageConfidence,
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
        </div>
      </div>

      {/* Running/Failed Status */}
      {batch.status === "running" && (
        <Card className="p-4">
          <div className="flex items-center gap-6 text-sm text-stone-600 dark:text-stone-400 mb-4">
            <div className="flex items-center gap-2">
              <Target className="w-4 h-4" />
              <span>Model: {batch.custom_model?.name || "Unknown"}</span>
            </div>
            {batch.custom_model && (
              <div>
                Target: {batch.custom_model.tag.key}:{" "}
                {batch.custom_model.tag.value}
              </div>
            )}
            <div>Threshold: {(batch.confidence_threshold * 100).toFixed(0)}%</div>
          </div>

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
            complete={batch.processed_clips}
            className="mb-2"
          />
          <div className="text-sm text-stone-500">
            {batch.total_predictions} predictions generated
          </div>
        </Card>
      )}

      {batch.status === "failed" && batch.error_message && (
        <Card className="p-4">
          <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
            <p className="text-sm text-red-600 dark:text-red-400">
              {batch.error_message}
            </p>
          </div>
        </Card>
      )}

      {/* Completed Status - Summary View */}
      {batch.status === "completed" && (
        <div className="grid grid-cols-12 gap-6">
          {/* Left Column - Main Summary */}
          <div className="col-span-8 space-y-6">
            {/* Detection Patterns */}
            <Card className="p-6">
              <h3 className="text-lg font-semibold text-stone-900 dark:text-stone-100 mb-6">
                Detection Patterns
              </h3>
              <DetectionVisualizationPanel
                batchUuid={batch.uuid}
                showLegend={true}
              />
            </Card>

            {/* Statistics */}
            <Card className="p-6">
              <h3 className="text-lg font-semibold text-stone-900 dark:text-stone-100 mb-6">
                Prediction Summary
              </h3>
              <div className="space-y-1">
                <StatRow
                  label="Total Predictions"
                  value={stats.totalPredictions.toLocaleString()}
                />
                <StatRow
                  label="Positive Predictions"
                  value={`${stats.positiveCount.toLocaleString()} (${stats.positiveRate.toFixed(1)}%)`}
                  color="emerald"
                />
                <StatRow
                  label="Negative Predictions"
                  value={`${stats.negativeCount.toLocaleString()} (${stats.negativeRate.toFixed(1)}%)`}
                  color="stone"
                />
                <StatRow
                  label="Average Confidence"
                  value={`${stats.averageConfidence.toFixed(1)}%`}
                />
              </div>
            </Card>
          </div>

          {/* Right Column - Batch Info */}
          <div className="col-span-4 space-y-4">
            {/* Batch Information */}
            <Card className="p-4">
              <h4 className="text-sm font-semibold text-stone-900 dark:text-stone-100 mb-4">
                Batch Information
              </h4>
              <div className="space-y-3 text-sm">
                <div>
                  <div className="text-stone-500 dark:text-stone-400 mb-1">
                    Model
                  </div>
                  <div className="font-medium text-stone-900 dark:text-stone-100">
                    {batch.custom_model?.name || "Unknown"}
                  </div>
                </div>
                {batch.custom_model && (
                  <div>
                    <div className="text-stone-500 dark:text-stone-400 mb-1">
                      Target
                    </div>
                    <div className="font-medium text-stone-900 dark:text-stone-100">
                      {batch.custom_model.tag.key}: {batch.custom_model.tag.value}
                    </div>
                  </div>
                )}
                <div>
                  <div className="text-stone-500 dark:text-stone-400 mb-1">
                    Confidence Threshold
                  </div>
                  <div className="font-medium text-stone-900 dark:text-stone-100">
                    {(batch.confidence_threshold * 100).toFixed(0)}%
                  </div>
                </div>
                <div>
                  <div className="text-stone-500 dark:text-stone-400 mb-1">
                    Total Clips Processed
                  </div>
                  <div className="font-medium text-stone-900 dark:text-stone-100">
                    {batch.total_clips.toLocaleString()}
                  </div>
                </div>
                {batch.duration_seconds !== null && (
                  <div>
                    <div className="text-stone-500 dark:text-stone-400 mb-1">
                      Duration
                    </div>
                    <div className="font-medium text-stone-900 dark:text-stone-100">
                      {Math.floor(batch.duration_seconds / 60)}m {batch.duration_seconds % 60}s
                    </div>
                  </div>
                )}
                {batch.completed_at && (
                  <div>
                    <div className="text-stone-500 dark:text-stone-400 mb-1">
                      Completed
                    </div>
                    <div className="font-medium text-stone-900 dark:text-stone-100">
                      {new Date(batch.completed_at).toLocaleString()}
                    </div>
                  </div>
                )}
              </div>
            </Card>

            {/* Export Button */}
            <Button
              variant="secondary"
              mode="outline"
              className="w-full"
              onClick={() => setIsExportDialogOpen(true)}
              disabled={stats.positiveCount === 0}
            >
              <Download className="w-4 h-4 mr-2" />
              Export Results
            </Button>
          </div>
        </div>
      )}

      {/* Export Dialog */}
      {batch && (
        <ExportInferenceBatchDialog
          isOpen={isExportDialogOpen}
          onClose={() => setIsExportDialogOpen(false)}
          onSuccess={handleExportSuccess}
          mlProjectUuid={mlProjectUuid}
          inferenceBatch={batch}
        />
      )}
    </div>
  );
}
