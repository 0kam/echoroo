"use client";

import { useEffect, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ClockIcon,
  GaugeIcon,
  Loader2Icon,
  MicIcon,
  Music2Icon,
  TargetIcon,
  XCircleIcon,
} from "lucide-react";
import toast from "react-hot-toast";

import api from "@/app/api";
import useFoundationModelRunProgress from "@/app/hooks/api/useFoundationModelRunProgress";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Loading from "@/lib/components/ui/Loading";

import type {
  FoundationModelRun,
  FoundationModelRunProgress,
  FoundationModelRunStatus,
} from "@/lib/types";

export interface FoundationModelProgressCardProps {
  /** The foundation model run to display progress for */
  run: FoundationModelRun;
  /** Whether to poll for progress updates (default: true when running) */
  enablePolling?: boolean;
  /** Callback when the run is cancelled */
  onCancelled?: () => void;
  /** Callback when the run completes */
  onComplete?: () => void;
}

const STATUS_CONFIG: Record<
  FoundationModelRunStatus,
  { label: string; className: string; icon?: React.ReactNode }
> = {
  queued: {
    label: "Queued",
    className: "bg-stone-100 text-stone-600 dark:bg-stone-700 dark:text-stone-300",
    icon: <ClockIcon className="h-3 w-3" />,
  },
  running: {
    label: "Running",
    className: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
    icon: <Loader2Icon className="h-3 w-3 animate-spin" />,
  },
  post_processing: {
    label: "Post-processing",
    className: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300",
    icon: <Loader2Icon className="h-3 w-3 animate-spin" />,
  },
  completed: {
    label: "Completed",
    className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
  },
  failed: {
    label: "Failed",
    className: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
  },
  cancelled: {
    label: "Cancelled",
    className: "bg-stone-200 text-stone-600 dark:bg-stone-600 dark:text-stone-400",
  },
};

function StatusBadge({ status }: { status: FoundationModelRunStatus }) {
  const config = STATUS_CONFIG[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${config.className}`}
    >
      {config.icon}
      {config.label}
    </span>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  if (minutes < 60) {
    return `${minutes}m ${remainingSeconds}s`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
}

function StatBox({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-stone-50 px-3 py-2 dark:bg-stone-800">
      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-stone-200 text-stone-600 dark:bg-stone-700 dark:text-stone-300">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs text-stone-500 dark:text-stone-400">
          {label}
        </p>
        <p className="truncate font-semibold text-stone-900 dark:text-stone-100">
          {typeof value === "number" ? value.toLocaleString() : value}
        </p>
      </div>
    </div>
  );
}

function ProgressBar({
  progress,
  className = "",
}: {
  progress: number;
  className?: string;
}) {
  const percentage = Math.min(100, Math.max(0, progress * 100));
  return (
    <div
      className={`h-3 w-full overflow-hidden rounded-full bg-stone-200 dark:bg-stone-700 ${className}`}
    >
      <div
        className="h-full rounded-full bg-emerald-500 transition-all duration-300 ease-out dark:bg-emerald-400"
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
}

/**
 * Card component that displays the progress of a foundation model run.
 * Shows a progress bar, stats grid (recordings processed, clips analyzed, detections found),
 * speed, elapsed time, ETA, and a cancel button.
 * Automatically polls for updates while the run is in progress.
 */
export default function FoundationModelProgressCard({
  run,
  enablePolling,
  onCancelled,
  onComplete,
}: FoundationModelProgressCardProps) {
  const queryClient = useQueryClient();

  const isActiveRun =
    run.status === "queued" ||
    run.status === "running" ||
    run.status === "post_processing";

  const shouldPoll = enablePolling ?? isActiveRun;

  const progressQuery = useFoundationModelRunProgress(run.uuid, {
    enabled: shouldPoll,
    refetchInterval: shouldPoll ? 2000 : false,
  });

  const progress: FoundationModelRunProgress | null = progressQuery.data ?? null;

  // Calculate elapsed time
  const elapsedSeconds = useMemo(() => {
    if (!run.started_on) return null;
    const start = new Date(run.started_on).getTime();
    const end = run.completed_on
      ? new Date(run.completed_on).getTime()
      : Date.now();
    return (end - start) / 1000;
  }, [run.started_on, run.completed_on]);

  // Handle completion callback
  const currentStatus = progress?.status ?? run.status;
  useEffect(() => {
    if (currentStatus === "completed" && onComplete) {
      onComplete();
    }
  }, [currentStatus, onComplete]);

  const cancelMutation = useMutation({
    mutationFn: async () => await api.foundationModels.cancelRun(run.uuid),
    onSuccess: () => {
      toast.success("Run cancelled");
      void queryClient.invalidateQueries({
        queryKey: ["foundation-models", "runs", run.uuid],
      });
      void queryClient.invalidateQueries({
        queryKey: ["foundation-models", "runs", run.uuid, "progress"],
      });
      onCancelled?.();
    },
    onError: (error: unknown) => {
      const message =
        error instanceof Error ? error.message : "Failed to cancel run";
      toast.error(message);
    },
  });

  const handleCancel = () => {
    cancelMutation.mutate();
  };

  // Determine the display values
  const displayProgress = progress?.progress ?? run.progress ?? 0;
  const displayStatus = progress?.status ?? run.status;
  const totalRecordings = progress?.total_recordings ?? run.total_recordings ?? 0;
  const processedRecordings =
    progress?.processed_recordings ?? run.processed_recordings ?? 0;
  const totalClips = progress?.total_clips ?? run.total_clips ?? 0;
  const totalDetections = progress?.total_detections ?? run.total_detections ?? 0;
  const speed = progress?.recordings_per_second ?? null;
  const eta = progress?.estimated_time_remaining_seconds ?? null;

  if (progressQuery.isLoading && !progress) {
    return (
      <Card>
        <Loading />
      </Card>
    );
  }

  return (
    <Card className="relative">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <h3 className="text-base font-semibold text-stone-900 dark:text-stone-100">
            {run.foundation_model?.display_name ?? "Foundation Model"}{" "}
            {run.foundation_model?.version && (
              <span className="text-sm font-normal text-stone-500">
                v{run.foundation_model.version}
              </span>
            )}
          </h3>
          <StatusBadge status={displayStatus} />
        </div>
        {isActiveRun && (
          <Button
            mode="ghost"
            variant="danger"
            onClick={handleCancel}
            disabled={cancelMutation.isPending}
            padding="p-2"
          >
            {cancelMutation.isPending ? (
              <Loader2Icon className="h-4 w-4 animate-spin" />
            ) : (
              <XCircleIcon className="h-4 w-4" />
            )}
            <span className="ml-1.5">Cancel</span>
          </Button>
        )}
      </div>

      {/* Progress Bar Section */}
      <div className="mt-4 space-y-2">
        <div className="flex items-center justify-between text-sm">
          <span className="text-stone-600 dark:text-stone-400">
            {processedRecordings.toLocaleString()} / {totalRecordings.toLocaleString()} recordings
          </span>
          <span className="font-medium text-stone-900 dark:text-stone-100">
            {(displayProgress * 100).toFixed(1)}%
          </span>
        </div>
        <ProgressBar progress={displayProgress} />
      </div>

      {/* Stats Grid */}
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatBox
          icon={<MicIcon className="h-4 w-4" />}
          label="Recordings"
          value={`${processedRecordings.toLocaleString()} / ${totalRecordings.toLocaleString()}`}
        />
        <StatBox
          icon={<Music2Icon className="h-4 w-4" />}
          label="Clips analyzed"
          value={totalClips}
        />
        <StatBox
          icon={<TargetIcon className="h-4 w-4" />}
          label="Detections"
          value={totalDetections}
        />
        <StatBox
          icon={<GaugeIcon className="h-4 w-4" />}
          label="Threshold"
          value={`${(run.confidence_threshold * 100).toFixed(0)}%`}
        />
      </div>

      {/* Speed, Elapsed Time, ETA */}
      <div className="mt-4 flex flex-wrap items-center gap-4 text-sm text-stone-600 dark:text-stone-400">
        {speed !== null && speed > 0 && (
          <div className="flex items-center gap-1.5">
            <GaugeIcon className="h-4 w-4" />
            <span>
              {speed.toFixed(2)} rec/s
            </span>
          </div>
        )}
        {elapsedSeconds !== null && (
          <div className="flex items-center gap-1.5">
            <ClockIcon className="h-4 w-4" />
            <span>Elapsed: {formatDuration(elapsedSeconds)}</span>
          </div>
        )}
        {eta !== null && eta > 0 && isActiveRun && (
          <div className="flex items-center gap-1.5">
            <ClockIcon className="h-4 w-4" />
            <span>ETA: {formatDuration(eta)}</span>
          </div>
        )}
      </div>

      {/* Error Message */}
      {run.status === "failed" && run.error && (
        <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
          <p className="font-medium">Run failed</p>
          <p className="mt-1">
            {typeof run.error === "object" && "message" in run.error
              ? String(run.error.message)
              : JSON.stringify(run.error)}
          </p>
        </div>
      )}

      {/* Progress Message */}
      {progress?.message && isActiveRun && (
        <div className="mt-3 rounded-lg bg-stone-50 p-2 text-sm text-stone-600 dark:bg-stone-800 dark:text-stone-400">
          {progress.message}
        </div>
      )}
    </Card>
  );
}
