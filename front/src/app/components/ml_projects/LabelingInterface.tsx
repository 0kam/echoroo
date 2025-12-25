"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";

import {
  CheckIcon,
  CloseIcon,
  NextIcon,
  PreviousIcon,
  AudioIcon,
  HelpIcon,
} from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import ShortcutHelper from "@/lib/components/ShortcutHelper";

import type { SearchResult, SearchResultLabel, Shortcut } from "@/lib/types";

interface LabelingInterfaceProps {
  results: SearchResult[];
  currentIndex: number;
  isLoading?: boolean;
  onLabel: (uuid: string, label: SearchResultLabel) => Promise<void>;
  onNavigate: (index: number) => void;
  SpectrogramComponent?: React.ReactNode;
  PlayerComponent?: React.ReactNode;
}

const LABEL_CONFIG: Record<
  Exclude<SearchResultLabel, "unlabeled">,
  { label: string; shortcut: string; className: string; icon: React.ReactNode }
> = {
  positive: {
    label: "Positive",
    shortcut: "1",
    className: "bg-emerald-600 hover:bg-emerald-700 text-white border-emerald-700",
    icon: <CheckIcon className="w-5 h-5" />,
  },
  negative: {
    label: "Negative",
    shortcut: "2",
    className: "bg-rose-600 hover:bg-rose-700 text-white border-rose-700",
    icon: <CloseIcon className="w-5 h-5" />,
  },
  uncertain: {
    label: "Uncertain",
    shortcut: "3",
    className: "bg-amber-500 hover:bg-amber-600 text-white border-amber-600",
    icon: <HelpIcon className="w-5 h-5" />,
  },
  skipped: {
    label: "Skip",
    shortcut: "s",
    className: "bg-stone-500 hover:bg-stone-600 text-white border-stone-600",
    icon: <NextIcon className="w-5 h-5" />,
  },
};

const SHORTCUTS: Shortcut[] = [
  { shortcut: "1", label: "Positive", description: "Label as positive (target species present)" },
  { shortcut: "2", label: "Negative", description: "Label as negative (target species absent)" },
  { shortcut: "3", label: "Uncertain", description: "Label as uncertain (need review)" },
  { shortcut: "s", label: "Skip", description: "Skip this result for now" },
  { shortcut: "j", label: "Previous", description: "Go to previous result" },
  { shortcut: "k", label: "Next", description: "Go to next result" },
  { shortcut: "Space", label: "Play/Pause", description: "Toggle audio playback" },
];

function formatSimilarity(similarity: number): string {
  return `${(similarity * 100).toFixed(1)}%`;
}

function LabelBadge({ label }: { label: SearchResultLabel }) {
  if (label === "unlabeled") {
    return (
      <span className="px-2 py-0.5 text-xs font-medium rounded bg-stone-200 dark:bg-stone-700 text-stone-600 dark:text-stone-400">
        Unlabeled
      </span>
    );
  }
  const config = LABEL_CONFIG[label];
  return (
    <span className={`px-2 py-0.5 text-xs font-medium rounded ${config.className}`}>
      {config.label}
    </span>
  );
}

function ProgressBar({
  current,
  total,
  labeled,
}: {
  current: number;
  total: number;
  labeled: number;
}) {
  const progress = total > 0 ? (labeled / total) * 100 : 0;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-xs text-stone-500 dark:text-stone-400">
        <span>
          {current + 1} of {total}
        </span>
        <span>
          {labeled} labeled ({progress.toFixed(0)}%)
        </span>
      </div>
      <div className="h-2 bg-stone-200 dark:bg-stone-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-emerald-500 transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

export default function LabelingInterface({
  results,
  currentIndex,
  isLoading = false,
  onLabel,
  onNavigate,
  SpectrogramComponent,
  PlayerComponent,
}: LabelingInterfaceProps) {
  const [isLabeling, setIsLabeling] = useState(false);

  const currentResult = results[currentIndex];
  const labeledCount = useMemo(
    () => results.filter((r) => r.label !== "unlabeled").length,
    [results],
  );

  // Find next unlabeled result
  const findNextUnlabeled = useCallback(() => {
    for (let i = currentIndex + 1; i < results.length; i++) {
      if (results[i].label === "unlabeled") {
        return i;
      }
    }
    // Wrap around to the beginning
    for (let i = 0; i < currentIndex; i++) {
      if (results[i].label === "unlabeled") {
        return i;
      }
    }
    return -1;
  }, [results, currentIndex]);

  const handleLabel = useCallback(
    async (label: SearchResultLabel) => {
      if (!currentResult || isLabeling) return;

      setIsLabeling(true);
      try {
        await onLabel(currentResult.uuid, label);

        // Auto-advance to next unlabeled result
        const nextUnlabeled = findNextUnlabeled();
        if (nextUnlabeled >= 0 && nextUnlabeled !== currentIndex) {
          onNavigate(nextUnlabeled);
        } else if (currentIndex < results.length - 1) {
          onNavigate(currentIndex + 1);
        }
      } finally {
        setIsLabeling(false);
      }
    },
    [currentResult, isLabeling, onLabel, findNextUnlabeled, currentIndex, results.length, onNavigate],
  );

  const handlePrevious = useCallback(() => {
    if (currentIndex > 0) {
      onNavigate(currentIndex - 1);
    }
  }, [currentIndex, onNavigate]);

  const handleNext = useCallback(() => {
    if (currentIndex < results.length - 1) {
      onNavigate(currentIndex + 1);
    }
  }, [currentIndex, results.length, onNavigate]);

  // Keyboard shortcuts
  useHotkeys("1", () => handleLabel("positive"), { enabled: !isLabeling }, [handleLabel]);
  useHotkeys("2", () => handleLabel("negative"), { enabled: !isLabeling }, [handleLabel]);
  useHotkeys("3", () => handleLabel("uncertain"), { enabled: !isLabeling }, [handleLabel]);
  useHotkeys("s", () => handleLabel("skipped"), { enabled: !isLabeling }, [handleLabel]);
  useHotkeys("j", handlePrevious, [handlePrevious]);
  useHotkeys("k", handleNext, [handleNext]);

  if (!currentResult) {
    return (
      <Card className="p-8 text-center">
        <p className="text-stone-500">No results to label.</p>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Progress */}
      <ProgressBar
        current={currentIndex}
        total={results.length}
        labeled={labeledCount}
      />

      {/* Main Content */}
      <Card className="p-0 overflow-hidden">
        {/* Header with result info */}
        <div className="flex items-center justify-between px-4 py-3 bg-stone-50 dark:bg-stone-800 border-b border-stone-200 dark:border-stone-700">
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-stone-700 dark:text-stone-300">
              Rank #{currentResult.rank}
            </span>
            <span className="text-sm text-stone-500">
              Similarity: {formatSimilarity(currentResult.similarity)}
            </span>
            <LabelBadge label={currentResult.label} />
          </div>
          <ShortcutHelper shortcuts={SHORTCUTS} />
        </div>

        {/* Spectrogram Display */}
        <div className="aspect-[3/1] bg-stone-900 flex items-center justify-center">
          {SpectrogramComponent ?? (
            <div className="text-stone-500 flex flex-col items-center gap-2">
              <AudioIcon className="w-16 h-16" />
              <span className="text-sm">Spectrogram</span>
            </div>
          )}
        </div>

        {/* Audio Player */}
        <div className="px-4 py-3 bg-stone-50 dark:bg-stone-800 border-t border-stone-200 dark:border-stone-700">
          {PlayerComponent ?? (
            <div className="h-8 flex items-center justify-center text-sm text-stone-500">
              Audio Player
            </div>
          )}
        </div>

        {/* Clip Info */}
        <div className="px-4 py-2 text-xs text-stone-500 dark:text-stone-400 border-t border-stone-200 dark:border-stone-700">
          <span>
            Recording: {currentResult.clip?.recording?.path?.split("/").pop() ?? "Unknown"}
          </span>
          <span className="mx-2">|</span>
          <span>
            Time: {currentResult.clip?.start_time.toFixed(2)}s - {currentResult.clip?.end_time.toFixed(2)}s
          </span>
        </div>
      </Card>

      {/* Label Buttons */}
      <div className="grid grid-cols-4 gap-3">
        {(Object.entries(LABEL_CONFIG) as [Exclude<SearchResultLabel, "unlabeled">, typeof LABEL_CONFIG[keyof typeof LABEL_CONFIG]][]).map(
          ([label, config]) => (
            <button
              key={label}
              type="button"
              onClick={() => handleLabel(label)}
              disabled={isLabeling}
              className={`flex flex-col items-center justify-center gap-1 py-3 px-4 rounded-lg border-2 font-medium transition-all ${config.className} disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {config.icon}
              <span>{config.label}</span>
              <span className="text-xs opacity-75">({config.shortcut})</span>
            </button>
          ),
        )}
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <Button
          variant="secondary"
          onClick={handlePrevious}
          disabled={currentIndex === 0}
        >
          <PreviousIcon className="w-4 h-4 mr-1" />
          Previous (j)
        </Button>
        <span className="text-sm text-stone-500">
          {currentIndex + 1} / {results.length}
        </span>
        <Button
          variant="secondary"
          onClick={handleNext}
          disabled={currentIndex >= results.length - 1}
        >
          Next (k)
          <NextIcon className="w-4 h-4 ml-1" />
        </Button>
      </div>
    </div>
  );
}
