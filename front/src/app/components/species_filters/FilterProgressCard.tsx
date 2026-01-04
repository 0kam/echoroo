"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import classNames from "classnames";
import { useCallback, useEffect } from "react";
import toast from "react-hot-toast";

import api from "@/app/api";
import { CheckIcon, CloseIcon } from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import type {
  SpeciesFilterApplication,
  SpeciesFilterApplicationProgress,
  SpeciesFilterApplicationStatus,
} from "@/lib/types";

// ============================================================================
// Props Interface
// ============================================================================

interface FilterProgressCardProps {
  runUuid: string;
  applicationUuid: string;
  /** Initial application data (optional, for immediate display) */
  initialData?: SpeciesFilterApplication;
  /** Callback when filter completes */
  onComplete: () => void;
  /** Callback when filter is cancelled */
  onCancel: () => void;
}

// ============================================================================
// Status Styles
// ============================================================================

const STATUS_STYLES: Record<
  SpeciesFilterApplicationStatus,
  { bg: string; text: string; label: string }
> = {
  pending: {
    bg: "bg-stone-200 dark:bg-stone-700",
    text: "text-stone-700 dark:text-stone-300",
    label: "Pending",
  },
  running: {
    bg: "bg-blue-100 dark:bg-blue-900",
    text: "text-blue-700 dark:text-blue-300",
    label: "Running",
  },
  completed: {
    bg: "bg-emerald-100 dark:bg-emerald-900",
    text: "text-emerald-700 dark:text-emerald-300",
    label: "Completed",
  },
  failed: {
    bg: "bg-red-100 dark:bg-red-900",
    text: "text-red-700 dark:text-red-300",
    label: "Failed",
  },
  cancelled: {
    bg: "bg-stone-300 dark:bg-stone-600",
    text: "text-stone-600 dark:text-stone-400",
    label: "Cancelled",
  },
};

// ============================================================================
// Status Badge Component
// ============================================================================

function StatusBadge({ status }: { status: SpeciesFilterApplicationStatus }) {
  const style = STATUS_STYLES[status];
  return (
    <span
      className={classNames(
        "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium",
        style.bg,
        style.text,
        status === "running" && "animate-pulse",
      )}
    >
      {style.label}
    </span>
  );
}

// ============================================================================
// Progress Bar Component
// ============================================================================

function ProgressBar({ progress }: { progress: number }) {
  const percentage = Math.min(100, Math.max(0, progress * 100));
  return (
    <div className="w-full bg-stone-200 dark:bg-stone-700 rounded-full h-2.5 overflow-hidden">
      <div
        className={classNames(
          "h-2.5 rounded-full transition-all duration-300",
          percentage >= 100
            ? "bg-emerald-500 dark:bg-emerald-400"
            : "bg-blue-500 dark:bg-blue-400",
        )}
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
}

// ============================================================================
// Stat Box Component
// ============================================================================

function StatBox({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: number | string;
  icon: React.ReactNode;
  color: "emerald" | "stone" | "blue";
}) {
  const colorStyles = {
    emerald:
      "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300",
    stone: "bg-stone-100 dark:bg-stone-800 text-stone-700 dark:text-stone-300",
    blue: "bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300",
  };

  return (
    <div
      className={classNames(
        "flex flex-col items-center p-3 rounded-lg",
        colorStyles[color],
      )}
    >
      <div className="flex items-center gap-1.5 mb-1">
        {icon}
        <span className="text-xs font-medium uppercase tracking-wide">
          {label}
        </span>
      </div>
      <span className="text-lg font-bold">{value}</span>
    </div>
  );
}

// ============================================================================
// Main Component
// ============================================================================

export default function FilterProgressCard({
  runUuid,
  applicationUuid,
  initialData,
  onComplete,
  onCancel,
}: FilterProgressCardProps) {
  const queryClient = useQueryClient();

  // Fetch progress
  const {
    data: progress,
    isLoading,
    error,
  } = useQuery({
    queryKey: [
      "foundation_model_run",
      runUuid,
      "filter_application",
      applicationUuid,
      "progress",
    ],
    queryFn: () =>
      api.speciesFilters.getApplicationProgress(runUuid, applicationUuid),
    refetchInterval: (query) => {
      const data = query.state.data as SpeciesFilterApplicationProgress | undefined;
      // Poll every 2 seconds while running or pending
      if (data?.status === "running" || data?.status === "pending") {
        return 2000;
      }
      return false;
    },
    initialData: initialData
      ? {
          uuid: initialData.uuid,
          status: initialData.status,
          progress: initialData.progress,
          total_detections: initialData.total_detections ?? 0,
          filtered_detections: initialData.filtered_detections ?? 0,
          excluded_detections: initialData.excluded_detections ?? 0,
        }
      : undefined,
  });

  // Handle completion
  useEffect(() => {
    if (progress?.status === "completed") {
      // Invalidate related queries
      queryClient.invalidateQueries({
        queryKey: ["foundation_model_run", runUuid, "filter_applications"],
      });
      onComplete();
    }
  }, [progress?.status, runUuid, queryClient, onComplete]);

  // Cancel mutation
  const cancelMutation = useMutation({
    mutationFn: () =>
      api.speciesFilters.cancelApplication(runUuid, applicationUuid),
    onSuccess: () => {
      toast.success("Filter application cancelled");
      queryClient.invalidateQueries({
        queryKey: [
          "foundation_model_run",
          runUuid,
          "filter_application",
          applicationUuid,
        ],
      });
      onCancel();
    },
    onError: () => {
      toast.error("Failed to cancel filter application");
    },
  });

  const handleCancel = useCallback(() => {
    cancelMutation.mutate();
  }, [cancelMutation]);

  // Extract data for display
  const status = progress?.status ?? initialData?.status ?? "pending";
  const progressValue = progress?.progress ?? initialData?.progress ?? 0;
  const totalDetections =
    progress?.total_detections ?? initialData?.total_detections ?? 0;
  const filteredDetections =
    progress?.filtered_detections ?? initialData?.filtered_detections ?? 0;
  const excludedDetections =
    progress?.excluded_detections ?? initialData?.excluded_detections ?? 0;

  // Calculate pass rate
  const processedCount = filteredDetections + excludedDetections;
  const passRate =
    processedCount > 0
      ? ((filteredDetections / processedCount) * 100).toFixed(1)
      : "0.0";

  // Filter info from initial data
  const filterName =
    initialData?.species_filter?.display_name ?? "Species Filter";
  const filterVersion = initialData?.species_filter?.version ?? "";
  const threshold = initialData?.threshold ?? 0;

  const isRunning = status === "running" || status === "pending";
  const isFailed = status === "failed";

  return (
    <Card className="relative">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <StatusBadge status={status} />
            <span className="text-sm font-medium text-stone-900 dark:text-stone-100 truncate">
              {filterName}
              {filterVersion && (
                <span className="text-stone-500 dark:text-stone-400">
                  {" "}
                  v{filterVersion}
                </span>
              )}
            </span>
          </div>
          <p className="text-xs text-stone-500 dark:text-stone-400 mt-1">
            Threshold: {(threshold * 100).toFixed(0)}%
          </p>
        </div>
        {isRunning && (
          <Button
            mode="text"
            variant="danger"
            padding="p-1"
            onClick={handleCancel}
            disabled={cancelMutation.isPending}
            title="Cancel filter application"
          >
            <CloseIcon className="w-5 h-5" />
          </Button>
        )}
      </div>

      {/* Progress */}
      {(isRunning || status === "completed") && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-stone-500 dark:text-stone-400">
            <span>
              Processing {processedCount.toLocaleString()} /{" "}
              {totalDetections.toLocaleString()} detections
            </span>
            <span>{(progressValue * 100).toFixed(0)}%</span>
          </div>
          <ProgressBar progress={progressValue} />
        </div>
      )}

      {/* Live Statistics */}
      <div className="grid grid-cols-3 gap-3">
        <StatBox
          label="Included"
          value={filteredDetections.toLocaleString()}
          icon={<CheckIcon className="w-4 h-4" />}
          color="emerald"
        />
        <StatBox
          label="Excluded"
          value={excludedDetections.toLocaleString()}
          icon={<CloseIcon className="w-4 h-4" />}
          color="stone"
        />
        <StatBox
          label="Pass Rate"
          value={`${passRate}%`}
          icon={null}
          color="blue"
        />
      </div>

      {/* Error State */}
      {isFailed && (
        <div className="p-3 bg-red-50 dark:bg-red-950 rounded-lg text-sm text-red-700 dark:text-red-300">
          <p className="font-medium">Filter application failed</p>
          {initialData?.error && (
            <p className="mt-1 text-xs">
              {typeof initialData.error === "string"
                ? initialData.error
                : JSON.stringify(initialData.error)}
            </p>
          )}
        </div>
      )}

      {/* Loading overlay */}
      {isLoading && !progress && !initialData && (
        <div className="absolute inset-0 bg-white/50 dark:bg-stone-900/50 flex items-center justify-center rounded-md">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-emerald-500" />
        </div>
      )}
    </Card>
  );
}
