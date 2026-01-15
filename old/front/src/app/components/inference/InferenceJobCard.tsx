import classNames from "classnames";
import { useCallback, useEffect, useState } from "react";

import {
  CloseIcon,
  DatasetIcon,
  ModelIcon,
  TimeIcon,
} from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";

/** Local inference job type for UI representation */
export type InferenceJobStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface InferenceJobConfig {
  threshold: number;
  overlap: number;
  minConfidence: number;
  batchSize: number;
}

export interface InferenceJobUI {
  id: string;
  datasetUuid: string;
  datasetName: string;
  model: string;
  config: InferenceJobConfig;
  status: InferenceJobStatus;
  progress: number;
  startedAt: Date;
  completedAt?: Date;
  error?: string;
  recordingCount?: number;
  processedCount?: number;
}

const STATUS_STYLES: Record<
  InferenceJobStatus,
  { bg: string; text: string; label: string }
> = {
  pending: {
    bg: "bg-amber-100 dark:bg-amber-900",
    text: "text-amber-700 dark:text-amber-300",
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
    bg: "bg-rose-100 dark:bg-rose-900",
    text: "text-rose-700 dark:text-rose-300",
    label: "Failed",
  },
  cancelled: {
    bg: "bg-stone-100 dark:bg-stone-800",
    text: "text-stone-700 dark:text-stone-300",
    label: "Cancelled",
  },
};

function StatusBadge({ status }: { status: InferenceJobStatus }) {
  const style = STATUS_STYLES[status];
  return (
    <span
      className={classNames(
        "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium",
        style.bg,
        style.text,
      )}
    >
      {style.label}
    </span>
  );
}

function ProgressBar({ progress }: { progress: number }) {
  const percentage = Math.min(100, Math.max(0, progress));
  return (
    <div className="w-full bg-stone-200 dark:bg-stone-700 rounded-full h-2.5 overflow-hidden">
      <div
        className="bg-emerald-500 dark:bg-emerald-400 h-2.5 rounded-full transition-all duration-300"
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
}

function formatDuration(startTime: Date, endTime?: Date): string {
  const end = endTime ?? new Date();
  const diffMs = end.getTime() - startTime.getTime();
  const seconds = Math.floor(diffMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);

  if (hours > 0) {
    return `${hours}h ${minutes % 60}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`;
  }
  return `${seconds}s`;
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function InferenceJobCard({
  job,
  onCancel,
  onUpdate,
}: {
  job: InferenceJobUI;
  onCancel?: (jobId: string) => void;
  onUpdate?: (job: InferenceJobUI) => void;
}) {
  const [isCancelling, setIsCancelling] = useState(false);

  const handleCancel = useCallback(async () => {
    if (!onCancel) return;
    setIsCancelling(true);
    try {
      onCancel(job.id);
    } finally {
      setIsCancelling(false);
    }
  }, [job.id, onCancel]);

  // Simulate progress updates for running jobs (demo purposes)
  useEffect(() => {
    if (job.status !== "running" || !onUpdate) return;

    const interval = setInterval(() => {
      const newProgress = Math.min(100, job.progress + Math.random() * 5);
      if (newProgress >= 100) {
        onUpdate({
          ...job,
          progress: 100,
          status: "completed",
          completedAt: new Date(),
        });
      } else {
        onUpdate({
          ...job,
          progress: newProgress,
        });
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [job, onUpdate]);

  const isRunning = job.status === "running";
  const isPending = job.status === "pending";
  const canCancel = isRunning || isPending;

  return (
    <Card className="relative">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <StatusBadge status={job.status} />
            <span className="text-sm font-medium text-stone-900 dark:text-stone-100 truncate">
              {job.model}
            </span>
          </div>
        </div>
        {canCancel && (
          <Button
            mode="text"
            variant="danger"
            padding="p-1"
            onClick={handleCancel}
            disabled={isCancelling}
            title="Cancel job"
          >
            <CloseIcon className="w-5 h-5" />
          </Button>
        )}
      </div>

      <div className="flex flex-col gap-2 text-sm text-stone-600 dark:text-stone-400">
        <div className="flex items-center gap-2">
          <DatasetIcon className="w-4 h-4 flex-shrink-0" />
          <span className="truncate">{job.datasetName}</span>
        </div>
        <div className="flex items-center gap-2">
          <ModelIcon className="w-4 h-4 flex-shrink-0" />
          <span>
            Threshold: {job.config.threshold.toFixed(2)} | Overlap:{" "}
            {job.config.overlap.toFixed(2)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <TimeIcon className="w-4 h-4 flex-shrink-0" />
          <span>
            Started: {formatTime(job.startedAt)}
            {job.completedAt &&
              ` | Duration: ${formatDuration(job.startedAt, job.completedAt)}`}
            {isRunning && ` | Elapsed: ${formatDuration(job.startedAt)}`}
          </span>
        </div>
      </div>

      {(isRunning || job.status === "completed") && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-stone-500 dark:text-stone-400">
            <span>Progress</span>
            <span>{job.progress.toFixed(0)}%</span>
          </div>
          <ProgressBar progress={job.progress} />
        </div>
      )}

      {job.status === "failed" && job.error && (
        <div className="mt-2 p-2 bg-rose-50 dark:bg-rose-950 rounded text-sm text-rose-700 dark:text-rose-300">
          Error: {job.error}
        </div>
      )}

      {job.recordingCount !== undefined && (
        <div className="text-xs text-stone-500 dark:text-stone-400">
          {job.processedCount ?? 0} / {job.recordingCount} recordings processed
        </div>
      )}
    </Card>
  );
}
