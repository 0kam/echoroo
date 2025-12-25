"use client";

import classNames from "classnames";

import {
  CheckIcon,
  CloseIcon,
  DeleteIcon,
  ModelIcon,
  PlayIcon,
  TagIcon,
  TrainIcon,
  WarningIcon,
} from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";

import type { CustomModel, CustomModelStatus, CustomModelType } from "@/lib/types";

/**
 * Status badge configuration for custom models.
 */
const STATUS_CONFIG: Record<
  CustomModelStatus,
  { label: string; className: string; icon: React.ReactNode }
> = {
  draft: {
    label: "Draft",
    className: "bg-stone-100 text-stone-600 border-stone-300",
    icon: null,
  },
  training: {
    label: "Training",
    className: "bg-blue-100 text-blue-600 border-blue-300",
    icon: <TrainIcon className="w-3 h-3 animate-pulse" />,
  },
  trained: {
    label: "Trained",
    className: "bg-emerald-100 text-emerald-600 border-emerald-300",
    icon: <CheckIcon className="w-3 h-3" />,
  },
  failed: {
    label: "Failed",
    className: "bg-rose-100 text-rose-600 border-rose-300",
    icon: <CloseIcon className="w-3 h-3" />,
  },
  deployed: {
    label: "Deployed",
    className: "bg-purple-100 text-purple-600 border-purple-300",
    icon: <PlayIcon className="w-3 h-3" />,
  },
  archived: {
    label: "Archived",
    className: "bg-stone-200 text-stone-500 border-stone-400",
    icon: null,
  },
};

/**
 * Model type display names.
 */
const MODEL_TYPE_NAMES: Record<CustomModelType, string> = {
  logistic_regression: "Logistic Regression",
  svm_linear: "SVM (Linear)",
  mlp_small: "MLP (Small)",
  mlp_medium: "MLP (Medium)",
  random_forest: "Random Forest",
};

function StatusBadge({ status }: { status: CustomModelStatus }) {
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

function MetricCard({
  label,
  value,
  format = "percent",
}: {
  label: string;
  value: number | null;
  format?: "percent" | "number";
}) {
  const formattedValue =
    value !== null
      ? format === "percent"
        ? `${(value * 100).toFixed(1)}%`
        : value.toFixed(3)
      : "-";

  return (
    <div className="flex flex-col items-center p-2 bg-stone-50 dark:bg-stone-800 rounded">
      <span className="text-lg font-semibold text-stone-800 dark:text-stone-200">
        {formattedValue}
      </span>
      <span className="text-xs text-stone-500 dark:text-stone-400">{label}</span>
    </div>
  );
}

function TrainingProgress({
  progress,
  currentEpoch,
  totalEpochs,
}: {
  progress: number;
  currentEpoch?: number;
  totalEpochs?: number;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-xs text-stone-500 dark:text-stone-400">
        <span>Training Progress</span>
        <span>
          {currentEpoch !== undefined && totalEpochs !== undefined
            ? `Epoch ${currentEpoch}/${totalEpochs}`
            : `${progress.toFixed(0)}%`}
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

export default function CustomModelCard({
  customModel,
  trainingProgress,
  onTrain,
  onDeploy,
  onDelete,
}: {
  customModel: CustomModel;
  trainingProgress?: {
    progress: number;
    currentEpoch?: number;
    totalEpochs?: number;
  };
  onTrain?: () => void;
  onDeploy?: () => void;
  onDelete?: () => void;
}) {
  const canTrain = customModel.status === "draft" || customModel.status === "failed";
  const canDeploy = customModel.status === "trained";
  const isTraining = customModel.status === "training";

  return (
    <div className="flex flex-col gap-3 p-4 rounded-lg border border-stone-200 dark:border-stone-700 bg-white dark:bg-stone-800">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <ModelIcon className="w-5 h-5 text-stone-500" />
          <div>
            <h4 className="font-medium text-stone-800 dark:text-stone-200">
              {customModel.name}
            </h4>
            <p className="text-xs text-stone-500 dark:text-stone-400">
              {MODEL_TYPE_NAMES[customModel.model_type]}
            </p>
          </div>
        </div>
        <StatusBadge status={customModel.status} />
      </div>

      {/* Target Tag */}
      <div className="flex items-center gap-1 text-sm text-stone-600 dark:text-stone-400">
        <TagIcon className="w-4 h-4" />
        <span>{customModel.target_tag.value}</span>
      </div>

      {/* Training Progress (if training) */}
      {isTraining && trainingProgress && (
        <TrainingProgress
          progress={trainingProgress.progress}
          currentEpoch={trainingProgress.currentEpoch}
          totalEpochs={trainingProgress.totalEpochs}
        />
      )}

      {/* Error Message (if failed) */}
      {customModel.status === "failed" && customModel.error_message && (
        <div className="flex items-start gap-2 p-2 bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 rounded text-xs text-rose-700 dark:text-rose-300">
          <WarningIcon className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span className="line-clamp-2">{customModel.error_message}</span>
        </div>
      )}

      {/* Training Metrics (if trained or deployed) */}
      {(customModel.status === "trained" || customModel.status === "deployed") && (
        <div className="grid grid-cols-4 gap-2">
          <MetricCard label="Accuracy" value={customModel.accuracy} />
          <MetricCard label="Precision" value={customModel.precision} />
          <MetricCard label="Recall" value={customModel.recall} />
          <MetricCard label="F1 Score" value={customModel.f1_score} />
        </div>
      )}

      {/* Training Info */}
      <div className="flex items-center gap-4 text-xs text-stone-500 dark:text-stone-500">
        <span>
          Training: {customModel.training_samples.toLocaleString()} samples
        </span>
        <span>
          Validation: {customModel.validation_samples.toLocaleString()} samples
        </span>
      </div>

      {/* Timestamps */}
      {customModel.training_completed_on && (
        <div className="text-xs text-stone-400 dark:text-stone-600">
          Trained: {customModel.training_completed_on.toLocaleString()}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between pt-2 border-t border-stone-200 dark:border-stone-700">
        <div className="flex gap-2">
          {canTrain && (
            <Button
              variant="primary"
              padding="p-2"
              onClick={onTrain}
            >
              <TrainIcon className="w-4 h-4 mr-1" />
              Train
            </Button>
          )}
          {canDeploy && (
            <Button
              variant="success"
              padding="p-2"
              onClick={onDeploy}
            >
              <PlayIcon className="w-4 h-4 mr-1" />
              Deploy
            </Button>
          )}
        </div>
        <Button
          mode="text"
          variant="danger"
          padding="p-1"
          onClick={onDelete}
          disabled={isTraining}
        >
          <DeleteIcon className="w-4 h-4" />
        </Button>
      </div>
    </div>
  );
}
