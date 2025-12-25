"use client";

import { useCallback, useMemo, useState } from "react";
import classNames from "classnames";

import {
  AudioIcon,
  CheckIcon,
  CloseIcon,
  HelpIcon,
} from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";

import type {
  InferencePrediction,
  InferencePredictionReviewStatus,
} from "@/lib/types";

const REVIEW_STATUS_COLORS: Record<InferencePredictionReviewStatus, string> = {
  unreviewed: "border-stone-300 dark:border-stone-600",
  confirmed: "border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20",
  rejected: "border-rose-500 bg-rose-50 dark:bg-rose-900/20",
  uncertain: "border-amber-500 bg-amber-50 dark:bg-amber-900/20",
};

const REVIEW_STATUS_ICONS: Record<InferencePredictionReviewStatus, React.ReactNode> = {
  unreviewed: null,
  confirmed: <CheckIcon className="w-4 h-4 text-emerald-600" />,
  rejected: <CloseIcon className="w-4 h-4 text-rose-600" />,
  uncertain: <HelpIcon className="w-4 h-4 text-amber-600" />,
};

interface PredictionReviewGridProps {
  predictions: InferencePrediction[];
  page: number;
  pageSize: number;
  totalPredictions: number;
  selectedPredictions: Set<string>;
  onPredictionClick?: (prediction: InferencePrediction, index: number) => void;
  onToggleSelect?: (uuid: string) => void;
  onSelectAll?: () => void;
  onDeselectAll?: () => void;
  onBulkReview?: (status: InferencePredictionReviewStatus) => void;
  onPageChange?: (page: number) => void;
  filterStatus?: InferencePredictionReviewStatus | "all";
  onFilterChange?: (status: InferencePredictionReviewStatus | "all") => void;
}

function formatConfidence(confidence: number): string {
  return `${(confidence * 100).toFixed(0)}%`;
}

function PredictionCard({
  prediction,
  index,
  isSelected,
  spectrogramUrl,
  onClick,
  onToggleSelect,
}: {
  prediction: InferencePrediction;
  index: number;
  isSelected: boolean;
  spectrogramUrl?: string;
  onClick?: () => void;
  onToggleSelect?: () => void;
}) {
  return (
    <div
      className={classNames(
        "relative flex flex-col rounded-lg border-2 overflow-hidden cursor-pointer transition-all hover:shadow-md",
        REVIEW_STATUS_COLORS[prediction.review_status],
        isSelected && "ring-2 ring-blue-500 ring-offset-2",
      )}
    >
      {/* Selection Checkbox */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onToggleSelect?.();
        }}
        className={classNames(
          "absolute top-2 left-2 z-10 w-5 h-5 rounded border-2 flex items-center justify-center transition-colors",
          isSelected
            ? "bg-blue-500 border-blue-500 text-white"
            : "bg-white/80 dark:bg-stone-800/80 border-stone-400 dark:border-stone-500",
        )}
      >
        {isSelected && <CheckIcon className="w-3 h-3" />}
      </button>

      {/* Review Status Icon */}
      {prediction.review_status !== "unreviewed" && (
        <div className="absolute top-2 right-2 z-10 w-6 h-6 rounded-full bg-white dark:bg-stone-800 flex items-center justify-center shadow">
          {REVIEW_STATUS_ICONS[prediction.review_status]}
        </div>
      )}

      {/* Prediction Badge */}
      <div
        className={classNames(
          "absolute top-2 right-10 z-10 px-1.5 py-0.5 text-xs font-bold rounded",
          prediction.predicted_positive
            ? "bg-emerald-500 text-white"
            : "bg-stone-500 text-white",
        )}
      >
        {prediction.predicted_positive ? "+" : "-"}
      </div>

      {/* Spectrogram Thumbnail */}
      <button
        type="button"
        onClick={onClick}
        className="w-full aspect-[2/1] bg-stone-200 dark:bg-stone-700 flex items-center justify-center"
      >
        {spectrogramUrl ? (
          <img
            src={spectrogramUrl}
            alt={`Prediction ${index + 1}`}
            className="w-full h-full object-cover"
          />
        ) : (
          <AudioIcon className="w-8 h-8 text-stone-400" />
        )}
      </button>

      {/* Info */}
      <div className="px-2 py-1.5">
        <div className="flex items-center justify-between">
          <span className="text-xs text-stone-600 dark:text-stone-400">
            Confidence
          </span>
          <span
            className={classNames("text-xs font-bold", {
              "text-emerald-600 dark:text-emerald-400":
                prediction.confidence >= 0.8,
              "text-amber-600 dark:text-amber-400":
                prediction.confidence >= 0.5 && prediction.confidence < 0.8,
              "text-stone-600 dark:text-stone-400":
                prediction.confidence < 0.5,
            })}
          >
            {formatConfidence(prediction.confidence)}
          </span>
        </div>
      </div>
    </div>
  );
}

export default function PredictionReviewGrid({
  predictions,
  page,
  pageSize,
  totalPredictions,
  selectedPredictions,
  onPredictionClick,
  onToggleSelect,
  onSelectAll,
  onDeselectAll,
  onBulkReview,
  onPageChange,
  filterStatus = "all",
  onFilterChange,
}: PredictionReviewGridProps) {
  const totalPages = Math.ceil(totalPredictions / pageSize);

  const filteredPredictions = useMemo(() => {
    if (filterStatus === "all") return predictions;
    return predictions.filter((p) => p.review_status === filterStatus);
  }, [predictions, filterStatus]);

  const handleSelectAllOnPage = useCallback(() => {
    onSelectAll?.();
  }, [onSelectAll]);

  const handleDeselectAll = useCallback(() => {
    onDeselectAll?.();
  }, [onDeselectAll]);

  // Summary stats
  const stats = useMemo(() => {
    const confirmed = predictions.filter((p) => p.review_status === "confirmed").length;
    const rejected = predictions.filter((p) => p.review_status === "rejected").length;
    const uncertain = predictions.filter((p) => p.review_status === "uncertain").length;
    const unreviewed = predictions.filter((p) => p.review_status === "unreviewed").length;
    return { confirmed, rejected, uncertain, unreviewed };
  }, [predictions]);

  return (
    <div className="flex flex-col gap-4">
      {/* Summary Stats */}
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <span className="text-stone-600 dark:text-stone-400">
          Review Progress:
        </span>
        <span className="text-emerald-600 dark:text-emerald-400 font-medium">
          {stats.confirmed} Confirmed
        </span>
        <span className="text-rose-600 dark:text-rose-400 font-medium">
          {stats.rejected} Rejected
        </span>
        <span className="text-amber-600 dark:text-amber-400 font-medium">
          {stats.uncertain} Uncertain
        </span>
        <span className="text-stone-500 font-medium">
          {stats.unreviewed} Unreviewed
        </span>
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Filter Chips */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-stone-500">Filter:</span>
          {(["all", "unreviewed", "confirmed", "rejected", "uncertain"] as const).map(
            (status) => (
              <button
                key={status}
                type="button"
                onClick={() => onFilterChange?.(status)}
                className={classNames(
                  "px-2 py-1 text-xs rounded-full border transition-colors",
                  filterStatus === status
                    ? "bg-stone-800 dark:bg-stone-200 text-white dark:text-stone-800 border-stone-800 dark:border-stone-200"
                    : "bg-white dark:bg-stone-800 text-stone-600 dark:text-stone-400 border-stone-300 dark:border-stone-600 hover:bg-stone-100 dark:hover:bg-stone-700",
                )}
              >
                {status === "all"
                  ? "All"
                  : status.charAt(0).toUpperCase() + status.slice(1)}
              </button>
            ),
          )}
        </div>

        {/* Selection Actions */}
        {selectedPredictions.size > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-stone-600 dark:text-stone-400">
              {selectedPredictions.size} selected
            </span>
            <Button
              mode="text"
              variant="secondary"
              padding="p-1"
              onClick={handleDeselectAll}
            >
              Clear
            </Button>
            <div className="flex gap-1">
              <Button
                variant="success"
                padding="p-1.5"
                onClick={() => onBulkReview?.("confirmed")}
                title="Confirm selected"
              >
                <CheckIcon className="w-4 h-4" />
              </Button>
              <Button
                variant="danger"
                padding="p-1.5"
                onClick={() => onBulkReview?.("rejected")}
                title="Reject selected"
              >
                <CloseIcon className="w-4 h-4" />
              </Button>
              <Button
                variant="warning"
                padding="p-1.5"
                onClick={() => onBulkReview?.("uncertain")}
                title="Mark as uncertain"
              >
                <HelpIcon className="w-4 h-4" />
              </Button>
            </div>
          </div>
        )}

        {/* Bulk Select */}
        <div className="flex items-center gap-2">
          <Button
            mode="text"
            variant="secondary"
            padding="p-1"
            onClick={handleSelectAllOnPage}
          >
            Select Page
          </Button>
        </div>
      </div>

      {/* Predictions Grid */}
      {filteredPredictions.length === 0 ? (
        <Card className="p-8 text-center">
          <p className="text-stone-500">
            No predictions match the current filter.
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {filteredPredictions.map((prediction, index) => (
            <PredictionCard
              key={prediction.uuid}
              prediction={prediction}
              index={page * pageSize + index}
              isSelected={selectedPredictions.has(prediction.uuid)}
              onClick={() =>
                onPredictionClick?.(prediction, page * pageSize + index)
              }
              onToggleSelect={() => onToggleSelect?.(prediction.uuid)}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="secondary"
            padding="p-2"
            disabled={page === 0}
            onClick={() => onPageChange?.(page - 1)}
          >
            Previous
          </Button>
          <div className="flex items-center gap-1">
            {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
              let pageNum: number;
              if (totalPages <= 7) {
                pageNum = i;
              } else if (page < 4) {
                pageNum = i;
              } else if (page >= totalPages - 4) {
                pageNum = totalPages - 7 + i;
              } else {
                pageNum = page - 3 + i;
              }
              return (
                <button
                  key={pageNum}
                  type="button"
                  onClick={() => onPageChange?.(pageNum)}
                  className={classNames(
                    "w-8 h-8 text-sm rounded transition-colors",
                    page === pageNum
                      ? "bg-emerald-500 text-white"
                      : "bg-stone-100 dark:bg-stone-800 text-stone-600 dark:text-stone-400 hover:bg-stone-200 dark:hover:bg-stone-700",
                  )}
                >
                  {pageNum + 1}
                </button>
              );
            })}
          </div>
          <Button
            variant="secondary"
            padding="p-2"
            disabled={page >= totalPages - 1}
            onClick={() => onPageChange?.(page + 1)}
          >
            Next
          </Button>
        </div>
      )}

      {/* Stats */}
      <div className="text-center text-sm text-stone-500">
        Showing {page * pageSize + 1}-
        {Math.min((page + 1) * pageSize, totalPredictions)} of{" "}
        {totalPredictions} predictions
      </div>
    </div>
  );
}
