"use client";

import classNames from "classnames";
import {
  useCallback,
  useRef,
  useState,
  type MouseEvent,
  type KeyboardEvent,
} from "react";

import { COMPONENT_CONFIGS } from "./constants";
import type { CharacterInfo, DateTimeSelection } from "./types";

interface CharacterGridProps {
  /** The filename to display */
  filename: string;
  /** Current selections */
  selections: DateTimeSelection[];
  /** Callback when a range is selected */
  onSelectionComplete: (startIndex: number, endIndex: number) => void;
  /** Whether to disable selection */
  disabled?: boolean;
}

/**
 * Displays characters in a grid and allows drag-to-select
 */
export default function CharacterGrid({
  filename,
  selections,
  onSelectionComplete,
  disabled = false,
}: CharacterGridProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState<number | null>(null);
  const [dragEnd, setDragEnd] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Build character info array
  const characters: CharacterInfo[] = filename.split("").map((char, index) => {
    const selection = selections.find(
      (s) => index >= s.startIndex && index < s.endIndex,
    );
    return { char, index, selection };
  });

  // Calculate current drag range
  const getDragRange = useCallback(() => {
    if (dragStart === null || dragEnd === null) return null;
    const start = Math.min(dragStart, dragEnd);
    const end = Math.max(dragStart, dragEnd);
    return { start, end };
  }, [dragStart, dragEnd]);

  const dragRange = getDragRange();

  // Check if an index is in the current drag range
  const isInDragRange = useCallback(
    (index: number) => {
      if (!dragRange) return false;
      return index >= dragRange.start && index <= dragRange.end;
    },
    [dragRange],
  );

  // Check if selection would overlap with existing selections
  const wouldOverlap = useCallback(
    (start: number, end: number) => {
      return selections.some(
        (s) =>
          (start >= s.startIndex && start < s.endIndex) ||
          (end > s.startIndex && end <= s.endIndex) ||
          (start <= s.startIndex && end >= s.endIndex),
      );
    },
    [selections],
  );

  const hasOverlap =
    dragRange && wouldOverlap(dragRange.start, dragRange.end + 1);

  const handleMouseDown = useCallback(
    (e: MouseEvent, index: number) => {
      if (disabled) return;
      e.preventDefault();
      setIsDragging(true);
      setDragStart(index);
      setDragEnd(index);
    },
    [disabled],
  );

  const handleMouseEnter = useCallback(
    (index: number) => {
      if (isDragging) {
        setDragEnd(index);
      }
    },
    [isDragging],
  );

  const handleMouseUp = useCallback(() => {
    if (isDragging && dragStart !== null && dragEnd !== null) {
      const start = Math.min(dragStart, dragEnd);
      const end = Math.max(dragStart, dragEnd) + 1; // End is exclusive

      // Only trigger if not overlapping
      if (!wouldOverlap(start, end)) {
        onSelectionComplete(start, end);
      }
    }
    setIsDragging(false);
    setDragStart(null);
    setDragEnd(null);
  }, [isDragging, dragStart, dragEnd, wouldOverlap, onSelectionComplete]);

  // Handle keyboard navigation for accessibility
  const handleKeyDown = useCallback(
    (e: KeyboardEvent, index: number) => {
      if (disabled) return;

      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (dragStart === null) {
          setDragStart(index);
          setDragEnd(index);
        } else {
          const start = Math.min(dragStart, index);
          const end = Math.max(dragStart, index) + 1;
          if (!wouldOverlap(start, end)) {
            onSelectionComplete(start, end);
          }
          setDragStart(null);
          setDragEnd(null);
        }
      } else if (e.key === "Escape") {
        setDragStart(null);
        setDragEnd(null);
      }
    },
    [disabled, dragStart, wouldOverlap, onSelectionComplete],
  );

  return (
    <div
      ref={containerRef}
      className="relative select-none"
      onMouseUp={handleMouseUp}
      onMouseLeave={() => {
        if (isDragging) {
          handleMouseUp();
        }
      }}
    >
      {/* Instructions */}
      <p className="text-xs text-stone-500 dark:text-stone-400 mb-2">
        Drag to select characters, then assign a datetime component
      </p>

      {/* Character grid */}
      <div
        className={classNames(
          "flex flex-wrap gap-0 p-3 rounded-lg border",
          "bg-stone-50 dark:bg-stone-800",
          "border-stone-200 dark:border-stone-700",
          disabled && "opacity-50 cursor-not-allowed",
        )}
        role="application"
        aria-label="Character selection grid"
      >
        {characters.map(({ char, index, selection }) => {
          const inDrag = isInDragRange(index);
          const config = selection
            ? COMPONENT_CONFIGS[selection.type]
            : undefined;

          return (
            <div
              key={index}
              role="button"
              tabIndex={disabled ? -1 : 0}
              className={classNames(
                "relative inline-flex items-center justify-center",
                "w-6 h-8 font-mono text-base",
                "transition-colors duration-75",
                "cursor-pointer",
                // Base styling
                !selection && !inDrag && "text-stone-700 dark:text-stone-300",
                // Selection styling
                selection && [config?.bgColor, config?.textColor],
                // Drag highlight
                inDrag && !hasOverlap && "bg-emerald-200 dark:bg-emerald-700",
                inDrag && hasOverlap && "bg-red-200 dark:bg-red-700",
                // Hover when not selected
                !selection &&
                  !inDrag &&
                  "hover:bg-stone-200 dark:hover:bg-stone-700",
                // First/last char in selection gets rounded corners
                selection &&
                  index === selection.startIndex &&
                  "rounded-l-md border-l-2",
                selection &&
                  index === selection.endIndex - 1 &&
                  "rounded-r-md border-r-2",
                selection && config?.borderColor,
                // Disabled styling
                disabled && "cursor-not-allowed",
              )}
              onMouseDown={(e) => handleMouseDown(e, index)}
              onMouseEnter={() => handleMouseEnter(index)}
              onKeyDown={(e) => handleKeyDown(e, index)}
              aria-label={`Character "${char}" at position ${index + 1}${
                selection ? `, assigned as ${selection.type}` : ""
              }`}
              aria-pressed={!!selection}
            >
              {char}
              {/* Show component badge on first char of selection */}
              {selection && index === selection.startIndex && (
                <span
                  className={classNames(
                    "absolute -top-3 left-0",
                    "text-[10px] font-semibold px-1 rounded",
                    config?.bgColor,
                    config?.textColor,
                    "border",
                    config?.borderColor,
                  )}
                >
                  {config?.shortLabel}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Overlap warning */}
      {hasOverlap && (
        <p className="text-xs text-red-500 dark:text-red-400 mt-2">
          Selection overlaps with existing assignment
        </p>
      )}
    </div>
  );
}
