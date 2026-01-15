import classNames from "classnames";
import { useMemo } from "react";

import { PlayIcon, TimeIcon } from "@/lib/components/icons";
import * as ui from "@/lib/components/ui";

import type { Clip } from "@/lib/types";

/** Props for SearchResultCard component */
export interface SearchResultCardProps {
  /** The clip to display */
  clip: Clip;
  /** Similarity score between 0 and 1 */
  similarityScore: number;
  /** Whether this card is currently selected */
  isSelected?: boolean;
  /** Callback when the card is clicked */
  onClick?: () => void;
  /** Callback when the play button is clicked */
  onPlay?: () => void;
}

/**
 * Formats duration in seconds to a human-readable string
 */
function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds.toFixed(0)}s`;
}

/**
 * Returns a color class based on the similarity score
 */
function getScoreColorClass(score: number): string {
  if (score >= 0.9) return "text-emerald-500";
  if (score >= 0.7) return "text-green-500";
  if (score >= 0.5) return "text-yellow-500";
  if (score >= 0.3) return "text-orange-500";
  return "text-red-500";
}

/**
 * Card component for displaying a search result with similarity score.
 * Shows clip information including recording path, time range, and similarity score.
 */
export default function SearchResultCard({
  clip,
  similarityScore,
  isSelected = false,
  onClick,
  onPlay,
}: SearchResultCardProps) {
  const clipDuration = useMemo(
    () => clip.end_time - clip.start_time,
    [clip.end_time, clip.start_time],
  );

  const recordingName = useMemo(() => {
    const path = clip.recording.path;
    const parts = path.split("/");
    return parts[parts.length - 1] || path;
  }, [clip.recording.path]);

  const scorePercentage = useMemo(
    () => (similarityScore * 100).toFixed(1),
    [similarityScore],
  );

  return (
    <ui.Card
      className={classNames(
        "cursor-pointer transition-all hover:shadow-md",
        {
          "ring-2 ring-emerald-500": isSelected,
          "hover:border-stone-400 dark:hover:border-stone-600": !isSelected,
        },
      )}
      onClick={onClick}
    >
      {/* Similarity Score Badge */}
      <div className="flex items-center justify-between">
        <span
          className={classNames(
            "text-lg font-bold",
            getScoreColorClass(similarityScore),
          )}
        >
          {scorePercentage}%
        </span>
        {onPlay && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onPlay();
            }}
            className="p-1 rounded-full hover:bg-stone-200 dark:hover:bg-stone-700 transition-colors"
            aria-label="Play clip"
          >
            <PlayIcon className="w-5 h-5 text-emerald-500" />
          </button>
        )}
      </div>

      {/* Recording Info */}
      <div className="text-sm text-stone-600 dark:text-stone-400 truncate" title={clip.recording.path}>
        {recordingName}
      </div>

      {/* Time Range */}
      <div className="flex items-center gap-2 text-xs text-stone-500 dark:text-stone-500">
        <TimeIcon className="w-4 h-4" />
        <span>
          {clip.start_time.toFixed(2)}s - {clip.end_time.toFixed(2)}s
        </span>
        <span className="text-stone-400">({formatDuration(clipDuration)})</span>
      </div>

      {/* Similarity Bar */}
      <div className="w-full h-1.5 bg-stone-200 dark:bg-stone-700 rounded-full overflow-hidden">
        <div
          className={classNames("h-full rounded-full transition-all", {
            "bg-emerald-500": similarityScore >= 0.9,
            "bg-green-500": similarityScore >= 0.7 && similarityScore < 0.9,
            "bg-yellow-500": similarityScore >= 0.5 && similarityScore < 0.7,
            "bg-orange-500": similarityScore >= 0.3 && similarityScore < 0.5,
            "bg-red-500": similarityScore < 0.3,
          })}
          style={{ width: `${similarityScore * 100}%` }}
        />
      </div>
    </ui.Card>
  );
}
