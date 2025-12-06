"use client";

import classNames from "classnames";
import { useCallback, useEffect, useMemo, useState } from "react";

import Button from "@/lib/components/ui/Button";

import CharacterGrid from "./CharacterGrid";
import ComponentAssignPopover from "./ComponentAssignPopover";
import ComponentBadge from "./ComponentBadge";
import { COMPONENT_CONFIGS, SEPARATOR_CHARS } from "./constants";
import PatternPreview from "./PatternPreview";
import type {
  DateTimeComponentType,
  DateTimeParseResult,
  DateTimePatternBuilderProps,
  DateTimeSelection,
} from "./types";

/**
 * Interactive component for building datetime patterns from filenames
 */
export default function DateTimePatternBuilder({
  filename,
  initialPattern,
  onPatternChange,
  onParse,
}: DateTimePatternBuilderProps) {
  const [selections, setSelections] = useState<DateTimeSelection[]>([]);
  const [pendingSelection, setPendingSelection] = useState<{
    startIndex: number;
    endIndex: number;
  } | null>(null);
  const [showPopover, setShowPopover] = useState(false);
  const [parseResult, setParseResult] = useState<DateTimeParseResult | null>(
    null,
  );

  // Generate unique ID for selections
  const generateId = () =>
    `sel_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

  // Handle selection complete from CharacterGrid
  const handleSelectionComplete = useCallback(
    (startIndex: number, endIndex: number) => {
      setPendingSelection({ startIndex, endIndex });
      setShowPopover(true);
    },
    [],
  );

  // Handle component type assignment
  const handleComponentSelect = useCallback(
    (type: DateTimeComponentType) => {
      if (!pendingSelection) return;

      const text = filename.slice(
        pendingSelection.startIndex,
        pendingSelection.endIndex,
      );

      const newSelection: DateTimeSelection = {
        id: generateId(),
        startIndex: pendingSelection.startIndex,
        endIndex: pendingSelection.endIndex,
        type,
        text,
      };

      setSelections((prev) => [...prev, newSelection]);
      setShowPopover(false);
      setPendingSelection(null);
    },
    [filename, pendingSelection],
  );

  // Handle selection removal
  const handleRemoveSelection = useCallback((id: string) => {
    setSelections((prev) => prev.filter((s) => s.id !== id));
  }, []);

  // Handle popover close
  const handlePopoverClose = useCallback(() => {
    setShowPopover(false);
    setPendingSelection(null);
  }, []);

  // Reset all selections
  const handleReset = useCallback(() => {
    setSelections([]);
    setParseResult(null);
  }, []);

  // Generate regex pattern from selections
  // Uses named capture groups for datetime components and .*? for unselected parts
  const generatePattern = useCallback((): string => {
    if (selections.length === 0) return "";

    // Sort selections by start index
    const sortedSelections = [...selections].sort(
      (a, b) => a.startIndex - b.startIndex,
    );

    let pattern = "";
    let i = 0;

    // Build pattern from the beginning of filename
    while (i < filename.length) {
      const selection = sortedSelections.find(
        (s) => i >= s.startIndex && i < s.endIndex,
      );

      if (selection && i === selection.startIndex) {
        // Add named capture group for this component
        const config = COMPONENT_CONFIGS[selection.type];
        // Use named capture group: (?P<Y>\d{4}) for year, etc.
        pattern += `(?P<${config.regexGroup}>${config.regexPattern.slice(1, -1)})`;
        // Skip to end of selection
        i = selection.endIndex;
      } else {
        // Find the next selection or end of string
        const nextSelection = sortedSelections.find((s) => s.startIndex > i);
        const nextIndex = nextSelection ? nextSelection.startIndex : filename.length;

        if (nextIndex > i) {
          // Check if this unselected region contains only literal separators
          const unselectedPart = filename.slice(i, nextIndex);
          const isOnlySeparators = /^[\._\-:/\s]+$/.test(unselectedPart);

          if (isOnlySeparators) {
            // Escape special regex characters and use as literal
            const escaped = unselectedPart.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            pattern += escaped;
          } else {
            // Use non-greedy wildcard for variable parts
            pattern += ".*?";
          }
          i = nextIndex;
        } else {
          i++;
        }
      }
    }

    return pattern;
  }, [filename, selections]);

  // Parse the filename with current pattern
  const parseFilename = useCallback(
    (pattern: string): DateTimeParseResult => {
      if (!pattern || selections.length === 0) {
        return { success: false };
      }

      try {
        // Extract values based on selections
        const sortedSelections = [...selections].sort(
          (a, b) => a.startIndex - b.startIndex,
        );

        const values: Partial<
          Record<DateTimeComponentType, number>
        > = {};

        for (const selection of sortedSelections) {
          const text = filename.slice(selection.startIndex, selection.endIndex);
          const num = parseInt(text, 10);

          if (isNaN(num)) {
            return {
              success: false,
              error: `Invalid ${selection.type}: "${text}" is not a number`,
            };
          }

          values[selection.type] = num;
        }

        // Validate values
        if (values.month !== undefined && (values.month < 1 || values.month > 12)) {
          return { success: false, error: `Invalid month: ${values.month}` };
        }
        if (values.day !== undefined && (values.day < 1 || values.day > 31)) {
          return { success: false, error: `Invalid day: ${values.day}` };
        }
        if (values.hour !== undefined && (values.hour < 0 || values.hour > 23)) {
          return { success: false, error: `Invalid hour: ${values.hour}` };
        }
        if (
          values.minute !== undefined &&
          (values.minute < 0 || values.minute > 59)
        ) {
          return { success: false, error: `Invalid minute: ${values.minute}` };
        }
        if (
          values.second !== undefined &&
          (values.second < 0 || values.second > 59)
        ) {
          return { success: false, error: `Invalid second: ${values.second}` };
        }

        // Build date (using defaults for missing components)
        const year = values.year ?? new Date().getFullYear();
        const month = (values.month ?? 1) - 1; // JS months are 0-based
        const day = values.day ?? 1;
        const hour = values.hour ?? 0;
        const minute = values.minute ?? 0;
        const second = values.second ?? 0;

        const date = new Date(year, month, day, hour, minute, second);

        // Validate the date is real
        if (
          date.getFullYear() !== year ||
          date.getMonth() !== month ||
          date.getDate() !== day
        ) {
          return { success: false, error: "Invalid date combination" };
        }

        return { success: true, date };
      } catch (e) {
        return {
          success: false,
          error: e instanceof Error ? e.message : "Parse error",
        };
      }
    },
    [filename, selections],
  );

  // Memoize the pattern
  const pattern = useMemo(() => generatePattern(), [generatePattern]);

  // Update parse result when pattern changes
  useEffect(() => {
    const result = parseFilename(pattern);
    setParseResult(result);
    onParse?.(result);
  }, [pattern, parseFilename, onParse]);

  // Notify parent of pattern changes
  useEffect(() => {
    onPatternChange(pattern, "regex");
  }, [pattern, onPatternChange]);

  // Get selected text for popover
  const selectedText = pendingSelection
    ? filename.slice(pendingSelection.startIndex, pendingSelection.endIndex)
    : "";

  // Sort selections for badge display
  const sortedSelections = useMemo(
    () => [...selections].sort((a, b) => a.startIndex - b.startIndex),
    [selections],
  );

  return (
    <div className="flex flex-col gap-6">
      {/* Filename display */}
      <div>
        <label className="text-sm font-medium text-stone-700 dark:text-stone-300 mb-2 block">
          Sample Filename
        </label>
        <div
          className={classNames(
            "px-4 py-3 rounded-lg font-mono text-lg",
            "bg-stone-100 dark:bg-stone-900",
            "text-stone-900 dark:text-stone-100",
            "border border-stone-200 dark:border-stone-700",
          )}
        >
          {filename}
        </div>
      </div>

      {/* Character selection grid */}
      <CharacterGrid
        filename={filename}
        selections={selections}
        onSelectionComplete={handleSelectionComplete}
      />

      {/* Component assignment popover */}
      <ComponentAssignPopover
        isOpen={showPopover}
        onClose={handlePopoverClose}
        onSelect={handleComponentSelect}
        selectedText={selectedText}
        existingSelections={selections}
      />

      {/* Selected components */}
      {sortedSelections.length > 0 && (
        <div>
          <label className="text-sm font-medium text-stone-700 dark:text-stone-300 mb-2 block">
            Selected Components
          </label>
          <div className="flex flex-wrap gap-2">
            {sortedSelections.map((selection) => (
              <ComponentBadge
                key={selection.id}
                selection={selection}
                onRemove={handleRemoveSelection}
              />
            ))}
          </div>
        </div>
      )}

      {/* Pattern preview */}
      <PatternPreview
        pattern={pattern}
        patternType="strptime"
        parseResult={parseResult}
      />

      {/* Action buttons */}
      <div className="flex justify-end gap-3">
        <Button
          type="button"
          mode="outline"
          variant="secondary"
          onClick={handleReset}
          disabled={selections.length === 0}
        >
          Reset
        </Button>
      </div>
    </div>
  );
}
