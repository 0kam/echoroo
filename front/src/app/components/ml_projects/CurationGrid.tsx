"use client";

import { useCallback, useMemo, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import classNames from "classnames";

import {
  AudioIcon,
  CheckIcon,
  CloseIcon,
  HelpIcon,
  NextIcon,
  AddIcon,
  PlayIcon,
  PauseIcon,
} from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import ShortcutHelper from "@/lib/components/ShortcutHelper";

import type { SearchResult, CurationLabel, Shortcut } from "@/lib/types";

// Label configuration for curation with extended labels
const LABEL_COLORS: Record<string, string> = {
  unlabeled: "border-stone-300 dark:border-stone-600",
  positive: "border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20",
  negative: "border-rose-500 bg-rose-50 dark:bg-rose-900/20",
  uncertain: "border-amber-500 bg-amber-50 dark:bg-amber-900/20",
  skipped: "border-stone-400 bg-stone-100 dark:bg-stone-800",
  positive_reference: "border-blue-500 bg-blue-50 dark:bg-blue-900/20 ring-2 ring-blue-400",
  negative_reference: "border-purple-500 bg-purple-50 dark:bg-purple-900/20 ring-2 ring-purple-400",
};

const LABEL_ICONS: Record<string, React.ReactNode> = {
  unlabeled: null,
  positive: <CheckIcon className="w-4 h-4 text-emerald-600" />,
  negative: <CloseIcon className="w-4 h-4 text-rose-600" />,
  uncertain: <HelpIcon className="w-4 h-4 text-amber-600" />,
  skipped: <NextIcon className="w-4 h-4 text-stone-500" />,
  positive_reference: <AddIcon className="w-4 h-4 text-blue-600" />,
  negative_reference: <CloseIcon className="w-4 h-4 text-purple-600" />,
};

const LABEL_DISPLAY: Record<string, string> = {
  unlabeled: "Unlabeled",
  positive: "Yes",
  negative: "No",
  uncertain: "Uncertain",
  skipped: "Skipped",
  positive_reference: "+ Reference",
  negative_reference: "- Reference",
};

const CURATION_SHORTCUTS: Shortcut[] = [
  { shortcut: "p", label: "Positive (Yes)", description: "Label as positive" },
  { shortcut: "n", label: "Negative (No)", description: "Label as negative" },
  { shortcut: "u", label: "Uncertain", description: "Label as uncertain" },
  { shortcut: "s", label: "Skip", description: "Skip this result" },
  { shortcut: "+", label: "Positive Reference", description: "Mark as positive training reference" },
  { shortcut: "-", label: "Negative Reference", description: "Mark as negative training reference" },
  { shortcut: "a", label: "Select All", description: "Select all visible results" },
  { shortcut: "Escape", label: "Clear Selection", description: "Clear all selections" },
];

interface CurationGridProps {
  results: SearchResult[];
  page: number;
  pageSize: number;
  totalResults: number;
  selectedResults: Set<string>;
  isLabeling?: boolean;
  onResultClick?: (result: SearchResult, index: number) => void;
  onToggleSelect?: (uuid: string) => void;
  onSelectAll?: () => void;
  onDeselectAll?: () => void;
  onBulkLabel?: (label: CurationLabel) => void;
  onPageChange?: (page: number) => void;
  onPlayAudio?: (result: SearchResult) => void;
  filterLabel?: string;
  onFilterChange?: (label: string) => void;
  similarityRange?: [number, number];
  onSimilarityRangeChange?: (range: [number, number]) => void;
}

function formatSimilarity(similarity: number): string {
  return `${(similarity * 100).toFixed(0)}%`;
}

function ResultCard({
  result,
  index,
  isSelected,
  spectrogramUrl,
  isPlaying,
  onClick,
  onToggleSelect,
  onPlayAudio,
}: {
  result: SearchResult;
  index: number;
  isSelected: boolean;
  spectrogramUrl?: string;
  isPlaying?: boolean;
  onClick?: () => void;
  onToggleSelect?: () => void;
  onPlayAudio?: () => void;
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

      {/* Audio Play Button */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onPlayAudio?.();
        }}
        className="absolute top-2 right-10 z-10 w-6 h-6 rounded-full bg-white/80 dark:bg-stone-800/80 flex items-center justify-center shadow hover:bg-emerald-100 dark:hover:bg-emerald-900/50 transition-colors"
      >
        {isPlaying ? (
          <PauseIcon className="w-3 h-3 text-emerald-600" />
        ) : (
          <PlayIcon className="w-3 h-3 text-stone-600 dark:text-stone-300" />
        )}
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
        {result.label !== "unlabeled" && (
          <div className="mt-0.5">
            <span className="text-xs text-stone-500 dark:text-stone-400">
              {LABEL_DISPLAY[result.label]}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function LabelButton({
  label,
  shortcut,
  icon,
  className,
  onClick,
  disabled,
}: {
  label: string;
  shortcut: string;
  icon: React.ReactNode;
  className: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={classNames(
        "flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
        className,
      )}
    >
      {icon}
      <span>{label}</span>
      <span className="ml-1 text-xs opacity-75">({shortcut})</span>
    </button>
  );
}

export default function CurationGrid({
  results,
  page,
  pageSize,
  totalResults,
  selectedResults,
  isLabeling = false,
  onResultClick,
  onToggleSelect,
  onSelectAll,
  onDeselectAll,
  onBulkLabel,
  onPageChange,
  onPlayAudio,
  filterLabel = "all",
  onFilterChange,
  similarityRange = [0, 1],
  onSimilarityRangeChange,
}: CurationGridProps) {
  const totalPages = Math.ceil(totalResults / pageSize);
  const [playingUuid, setPlayingUuid] = useState<string | null>(null);

  const filteredResults = useMemo(() => {
    let filtered = results;
    if (filterLabel !== "all") {
      filtered = filtered.filter((r) => r.label === filterLabel);
    }
    filtered = filtered.filter(
      (r) => r.similarity >= similarityRange[0] && r.similarity <= similarityRange[1]
    );
    return filtered;
  }, [results, filterLabel, similarityRange]);

  const handleSelectAllOnPage = useCallback(() => {
    onSelectAll?.();
  }, [onSelectAll]);

  const handleDeselectAll = useCallback(() => {
    onDeselectAll?.();
  }, [onDeselectAll]);

  const handlePlayAudio = useCallback((result: SearchResult) => {
    if (playingUuid === result.uuid) {
      setPlayingUuid(null);
    } else {
      setPlayingUuid(result.uuid);
      onPlayAudio?.(result);
    }
  }, [playingUuid, onPlayAudio]);

  // Keyboard shortcuts
  useHotkeys("p", () => onBulkLabel?.("positive"), { enabled: !isLabeling && selectedResults.size > 0 }, [onBulkLabel]);
  useHotkeys("n", () => onBulkLabel?.("negative"), { enabled: !isLabeling && selectedResults.size > 0 }, [onBulkLabel]);
  useHotkeys("u", () => onBulkLabel?.("uncertain"), { enabled: !isLabeling && selectedResults.size > 0 }, [onBulkLabel]);
  useHotkeys("s", () => onBulkLabel?.("skipped"), { enabled: !isLabeling && selectedResults.size > 0 }, [onBulkLabel]);
  useHotkeys("shift+=", () => onBulkLabel?.("positive_reference"), { enabled: !isLabeling && selectedResults.size > 0 }, [onBulkLabel]);
  useHotkeys("-", () => onBulkLabel?.("negative_reference"), { enabled: !isLabeling && selectedResults.size > 0 }, [onBulkLabel]);
  useHotkeys("a", handleSelectAllOnPage, [handleSelectAllOnPage]);
  useHotkeys("escape", handleDeselectAll, [handleDeselectAll]);

  const allLabels = ["all", "unlabeled", "positive", "negative", "uncertain", "skipped", "positive_reference", "negative_reference"];

  return (
    <div className="flex flex-col gap-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 bg-stone-50 dark:bg-stone-800 rounded-lg">
        {/* Filter Chips */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-stone-500">Filter:</span>
          {allLabels.map((label) => (
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
              {label === "all" ? "All" : LABEL_DISPLAY[label]}
            </button>
          ))}
        </div>

        {/* Shortcuts Helper */}
        <ShortcutHelper shortcuts={CURATION_SHORTCUTS} />
      </div>

      {/* Selection Actions */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Bulk Select */}
        <div className="flex items-center gap-2">
          <Button
            mode="text"
            variant="secondary"
            padding="p-1"
            onClick={handleSelectAllOnPage}
          >
            Select All (A)
          </Button>
          {selectedResults.size > 0 && (
            <Button
              mode="text"
              variant="secondary"
              padding="p-1"
              onClick={handleDeselectAll}
            >
              Clear ({selectedResults.size})
            </Button>
          )}
        </div>

        {/* Label Buttons - Visible when selection > 0 */}
        {selectedResults.size > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-stone-600 dark:text-stone-400">
              {selectedResults.size} selected:
            </span>
            <LabelButton
              label="Yes"
              shortcut="P"
              icon={<CheckIcon className="w-4 h-4" />}
              className="bg-emerald-100 hover:bg-emerald-200 dark:bg-emerald-900/30 dark:hover:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300"
              onClick={() => onBulkLabel?.("positive")}
              disabled={isLabeling}
            />
            <LabelButton
              label="No"
              shortcut="N"
              icon={<CloseIcon className="w-4 h-4" />}
              className="bg-rose-100 hover:bg-rose-200 dark:bg-rose-900/30 dark:hover:bg-rose-900/50 text-rose-700 dark:text-rose-300"
              onClick={() => onBulkLabel?.("negative")}
              disabled={isLabeling}
            />
            <LabelButton
              label="Uncertain"
              shortcut="U"
              icon={<HelpIcon className="w-4 h-4" />}
              className="bg-amber-100 hover:bg-amber-200 dark:bg-amber-900/30 dark:hover:bg-amber-900/50 text-amber-700 dark:text-amber-300"
              onClick={() => onBulkLabel?.("uncertain")}
              disabled={isLabeling}
            />
            <LabelButton
              label="Skip"
              shortcut="S"
              icon={<NextIcon className="w-4 h-4" />}
              className="bg-stone-200 hover:bg-stone-300 dark:bg-stone-700 dark:hover:bg-stone-600 text-stone-700 dark:text-stone-300"
              onClick={() => onBulkLabel?.("skipped")}
              disabled={isLabeling}
            />
            <div className="w-px h-6 bg-stone-300 dark:bg-stone-600" />
            <LabelButton
              label="+ Ref"
              shortcut="+"
              icon={<AddIcon className="w-4 h-4" />}
              className="bg-blue-100 hover:bg-blue-200 dark:bg-blue-900/30 dark:hover:bg-blue-900/50 text-blue-700 dark:text-blue-300"
              onClick={() => onBulkLabel?.("positive_reference")}
              disabled={isLabeling}
            />
            <LabelButton
              label="- Ref"
              shortcut="-"
              icon={<CloseIcon className="w-4 h-4" />}
              className="bg-purple-100 hover:bg-purple-200 dark:bg-purple-900/30 dark:hover:bg-purple-900/50 text-purple-700 dark:text-purple-300"
              onClick={() => onBulkLabel?.("negative_reference")}
              disabled={isLabeling}
            />
          </div>
        )}
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
              isPlaying={playingUuid === result.uuid}
              onClick={() => onResultClick?.(result, page * pageSize + index)}
              onToggleSelect={() => onToggleSelect?.(result.uuid)}
              onPlayAudio={() => handlePlayAudio(result)}
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
