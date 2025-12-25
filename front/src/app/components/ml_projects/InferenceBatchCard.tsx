"use client";

import classNames from "classnames";

import {
  CheckIcon,
  CloseIcon,
  DeleteIcon,
  ModelIcon,
  PlayIcon,
  SearchIcon,
  WarningIcon,
} from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";

import type { InferenceBatch, InferenceBatchStatus } from "@/lib/types";

/**
 * Status badge configuration for inference batches.
 */
const STATUS_CONFIG: Record<
  InferenceBatchStatus,
  { label: string; className: string; icon: React.ReactNode }
> = {
  pending: {
    label: "Pending",
    className: "bg-stone-100 text-stone-600 border-stone-300",
    icon: null,
  },
  running: {
    label: "Running",
    className: "bg-blue-100 text-blue-600 border-blue-300",
    icon: <PlayIcon className="w-3 h-3 animate-pulse" />,
  },
  completed: {
    label: "Completed",
    className: "bg-emerald-100 text-emerald-600 border-emerald-300",
    icon: <CheckIcon className="w-3 h-3" />,
  },
  failed: {
    label: "Failed",
    className: "bg-rose-100 text-rose-600 border-rose-300",
    icon: <CloseIcon className="w-3 h-3" />,
  },
  cancelled: {
    label: "Cancelled",
    className: "bg-stone-200 text-stone-500 border-stone-400",
    icon: null,
  },
};

function StatusBadge({ status }: { status: InferenceBatchStatus }) {
  const config = STATUS_CONFIG[status];
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full border ${config.className}`}
    >
      {config.icon}
      {config.label}
    </span>
  );
}

function ProgressBar({
  progress,
  processedItems,
  totalItems,
}: {
  progress: number;
  processedItems: number;
  totalItems: number;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-xs text-stone-500 dark:text-stone-400">
        <span>Progress</span>
        <span>
          {processedItems.toLocaleString()} / {totalItems.toLocaleString()} items
        </span>
      </div>
      <div className="h-2 bg-stone-200 dark:bg-stone-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 transition-all duration-300"
          style={{ width: `${Math.min(progress, 100)}%` }}
        />
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  variant = "default",
}: {
  label: string;
  value: number | string;
  variant?: "default" | "positive" | "info";
}) {
  const valueClass = classNames("text-lg font-semibold", {
    "text-stone-800 dark:text-stone-200": variant === "default",
    "text-emerald-600 dark:text-emerald-400": variant === "positive",
    "text-blue-600 dark:text-blue-400": variant === "info",
  });

  return (
    <div className="flex flex-col items-center p-2 bg-stone-50 dark:bg-stone-800 rounded">
      <span className={valueClass}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </span>
      <span className="text-xs text-stone-500 dark:text-stone-400">{label}</span>
    </div>
  );
}

export default function InferenceBatchCard({
  inferenceBatch,
  onStart,
  onViewPredictions,
  onDelete,
}: {
  inferenceBatch: InferenceBatch;
  onStart?: () => void;
  onViewPredictions?: () => void;
  onDelete?: () => void;
}) {
  const canStart = inferenceBatch.status === "pending";
  const canViewPredictions =
    inferenceBatch.status === "completed" ||
    (inferenceBatch.status === "running" && inferenceBatch.processed_items > 0);
  const isRunning = inferenceBatch.status === "running";

  const positiveRate =
    inferenceBatch.processed_items > 0
      ? (inferenceBatch.positive_predictions / inferenceBatch.processed_items) * 100
      : 0;

  return (
    <div className="flex flex-col gap-3 p-4 rounded-lg border border-stone-200 dark:border-stone-700 bg-white dark:bg-stone-800">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <SearchIcon className="w-5 h-5 text-stone-500" />
          <div>
            <h4 className="font-medium text-stone-800 dark:text-stone-200">
              {inferenceBatch.name}
            </h4>
            {inferenceBatch.description && (
              <p className="text-xs text-stone-500 dark:text-stone-400 line-clamp-1">
                {inferenceBatch.description}
              </p>
            )}
          </div>
        </div>
        <StatusBadge status={inferenceBatch.status} />
      </div>

      {/* Model Info */}
      <div className="flex items-center gap-1 text-sm text-stone-600 dark:text-stone-400">
        <ModelIcon className="w-4 h-4" />
        <span>{inferenceBatch.custom_model.name}</span>
        <span className="text-stone-400">-</span>
        <span className="text-xs">{inferenceBatch.custom_model.target_tag.value}</span>
      </div>

      {/* Progress (if running or completed) */}
      {(isRunning || inferenceBatch.status === "completed") && (
        <ProgressBar
          progress={inferenceBatch.progress}
          processedItems={inferenceBatch.processed_items}
          totalItems={inferenceBatch.total_items}
        />
      )}

      {/* Error Message (if failed) */}
      {inferenceBatch.status === "failed" && inferenceBatch.error_message && (
        <div className="flex items-start gap-2 p-2 bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 rounded text-xs text-rose-700 dark:text-rose-300">
          <WarningIcon className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="line-clamp-2">{inferenceBatch.error_message}</span>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-3 gap-2">
        <StatCard label="Total" value={inferenceBatch.total_items} />
        <StatCard
          label="Positive"
          value={inferenceBatch.positive_predictions}
          variant="positive"
        />
        <StatCard
          label="Rate"
          value={`${positiveRate.toFixed(1)}%`}
          variant="info"
        />
      </div>

      {/* Configuration */}
      <div className="flex items-center gap-4 text-xs text-stone-500 dark:text-stone-500">
        <span>Threshold: {(inferenceBatch.confidence_threshold * 100).toFixed(0)}%</span>
        <span>Batch Size: {inferenceBatch.batch_size}</span>
      </div>

      {/* Timestamps */}
      <div className="flex flex-wrap gap-3 text-xs text-stone-400 dark:text-stone-600">
        <span>Created: {inferenceBatch.created_on.toLocaleString()}</span>
        {inferenceBatch.started_on && (
          <span>Started: {inferenceBatch.started_on.toLocaleString()}</span>
        )}
        {inferenceBatch.completed_on && (
          <span>Completed: {inferenceBatch.completed_on.toLocaleString()}</span>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-2 border-t border-stone-200 dark:border-stone-700">
        <div className="flex gap-2">
          {canStart && (
            <Button variant="primary" padding="p-2" onClick={onStart}>
              <PlayIcon className="w-4 h-4 mr-1" />
              Start
            </Button>
          )}
          {canViewPredictions && (
            <Button variant="secondary" padding="p-2" onClick={onViewPredictions}>
              <SearchIcon className="w-4 h-4 mr-1" />
              View Predictions
            </Button>
          )}
        </div>
        <Button
          mode="text"
          variant="danger"
          padding="p-1"
          onClick={onDelete}
          disabled={isRunning}
        >
          <DeleteIcon className="w-4 h-4" />
        </Button>
      </div>
    </div>
  );
}
