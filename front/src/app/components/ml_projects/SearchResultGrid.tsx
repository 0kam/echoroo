"use client";

import { useCallback, useMemo, useState } from "react";
import classNames from "classnames";

import {
  AudioIcon,
  CheckIcon,
  CloseIcon,
  HelpIcon,
  NextIcon,
} from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";

import type { SearchResult, SearchResultLabel } from "@/lib/types";

const LABEL_COLORS: Record<SearchResultLabel, string> = {
  unlabeled: "border-stone-300 dark:border-stone-600",
  positive: "border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20",
  negative: "border-rose-500 bg-rose-50 dark:bg-rose-900/20",
  uncertain: "border-amber-500 bg-amber-50 dark:bg-amber-900/20",
  skipped: "border-stone-400 bg-stone-100 dark:bg-stone-800",
  positive_reference: "border-blue-500 bg-blue-50 dark:bg-blue-900/20 ring-2 ring-blue-400",
  negative_reference: "border-purple-500 bg-purple-50 dark:bg-purple-900/20 ring-2 ring-purple-400",
};

const LABEL_ICONS: Record<SearchResultLabel, React.ReactNode> = {
  unlabeled: null,
  positive: <CheckIcon className="w-4 h-4 text-emerald-600" />,
  negative: <CloseIcon className="w-4 h-4 text-rose-600" />,
  uncertain: <HelpIcon className="w-4 h-4 text-amber-600" />,
  skipped: <NextIcon className="w-4 h-4 text-stone-500" />,
  positive_reference: <CheckIcon className="w-4 h-4 text-blue-600" />,
  negative_reference: <CloseIcon className="w-4 h-4 text-purple-600" />,
};

interface SearchResultGridProps {
  results: SearchResult[];
  page: number;
  pageSize: number;
  totalResults: number;
  selectedResults: Set<string>;
  onResultClick?: (result: SearchResult, index: number) => void;
  onToggleSelect?: (uuid: string) => void;
  onSelectAll?: () => void;
  onDeselectAll?: () => void;
  onBulkLabel?: (label: SearchResultLabel) => void;
  onPageChange?: (page: number) => void;
  filterLabel?: SearchResultLabel | "all";
  onFilterChange?: (label: SearchResultLabel | "all") => void;
}

function formatSimilarity(similarity: number): string {
  return `${(similarity * 100).toFixed(0)}%`;
}

function ResultCard({
  result,
  index,
  isSelected,
  spectrogramUrl,
  onClick,
  onToggleSelect,
}: {
  result: SearchResult;
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
        LABEL_COLORS[result.label],
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

      {/* Label Icon */}
      {result.label !== "unlabeled" && (
        <div className="absolute top-2 right-2 z-10 w-6 h-6 rounded-full bg-white dark:bg-stone-800 flex items-center justify-center shadow">
          {LABEL_ICONS[result.label]}
        </div>
      )}

      {/* Spectrogram Thumbnail */}
      <button
        type="button"
        onClick={onClick}
        className="w-full aspect-[2/1] bg-stone-200 dark:bg-stone-700 flex items-center justify-center"
      >
        {spectrogramUrl ? (
          <img
            src={spectrogramUrl}
            alt={`Result ${result.rank}`}
            className="w-full h-full object-cover"
          />
        ) : (
          <AudioIcon className="w-8 h-8 text-stone-400" />
        )}
      </button>

      {/* Info */}
      <div className="px-2 py-1.5">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-stone-700 dark:text-stone-300">
            #{result.rank}
          </span>
          <span className="text-xs font-bold text-emerald-600 dark:text-emerald-400">
            {formatSimilarity(result.similarity)}
          </span>
        </div>
      </div>
    </div>
  );
}

export default function SearchResultGrid({
  results,
  page,
  pageSize,
  totalResults,
  selectedResults,
  onResultClick,
  onToggleSelect,
  onSelectAll,
  onDeselectAll,
  onBulkLabel,
  onPageChange,
  filterLabel = "all",
  onFilterChange,
}: SearchResultGridProps) {
  const totalPages = Math.ceil(totalResults / pageSize);

  const filteredResults = useMemo(() => {
    if (filterLabel === "all") return results;
    return results.filter((r) => r.label === filterLabel);
  }, [results, filterLabel]);

  const handleSelectAllOnPage = useCallback(() => {
    onSelectAll?.();
  }, [onSelectAll]);

  const handleDeselectAll = useCallback(() => {
    onDeselectAll?.();
  }, [onDeselectAll]);

  return (
    <div className="flex flex-col gap-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Filter Chips */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-stone-500">Filter:</span>
          {(["all", "unlabeled", "positive", "negative", "uncertain", "skipped"] as const).map(
            (label) => (
              <button
                key={label}
                type="button"
                onClick={() => onFilterChange?.(label)}
                className={classNames(
                  "px-2 py-1 text-xs rounded-full border transition-colors",
                  filterLabel === label
                    ? "bg-stone-800 dark:bg-stone-200 text-white dark:text-stone-800 border-stone-800 dark:border-stone-200"
                    : "bg-white dark:bg-stone-800 text-stone-600 dark:text-stone-400 border-stone-300 dark:border-stone-600 hover:bg-stone-100 dark:hover:bg-stone-700",
                )}
              >
                {label === "all" ? "All" : label.charAt(0).toUpperCase() + label.slice(1)}
              </button>
            ),
          )}
        </div>

        {/* Selection Actions */}
        {selectedResults.size > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-stone-600 dark:text-stone-400">
              {selectedResults.size} selected
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
                onClick={() => onBulkLabel?.("positive")}
              >
                <CheckIcon className="w-4 h-4" />
              </Button>
              <Button
                variant="danger"
                padding="p-1.5"
                onClick={() => onBulkLabel?.("negative")}
              >
                <CloseIcon className="w-4 h-4" />
              </Button>
              <Button
                variant="warning"
                padding="p-1.5"
                onClick={() => onBulkLabel?.("uncertain")}
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

      {/* Results Grid */}
      {filteredResults.length === 0 ? (
        <Card className="p-8 text-center">
          <p className="text-stone-500">No results match the current filter.</p>
        </Card>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {filteredResults.map((result, index) => (
            <ResultCard
              key={result.uuid}
              result={result}
              index={page * pageSize + index}
              isSelected={selectedResults.has(result.uuid)}
              onClick={() => onResultClick?.(result, page * pageSize + index)}
              onToggleSelect={() => onToggleSelect?.(result.uuid)}
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
        Showing {page * pageSize + 1}-{Math.min((page + 1) * pageSize, totalResults)} of{" "}
        {totalResults} results
      </div>
    </div>
  );
}
