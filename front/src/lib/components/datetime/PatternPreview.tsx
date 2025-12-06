"use client";

import classNames from "classnames";

import { CheckIcon, WarningIcon } from "@/lib/components/icons";

import type { DateTimeParseResult } from "./types";

interface PatternPreviewProps {
  /** The generated pattern */
  pattern: string;
  /** The pattern type */
  patternType: "strptime" | "regex";
  /** Parse result */
  parseResult: DateTimeParseResult | null;
  /** Whether parsing is in progress */
  isParsing?: boolean;
}

/**
 * Displays the generated pattern and parse preview
 */
export default function PatternPreview({
  pattern,
  patternType,
  parseResult,
  isParsing = false,
}: PatternPreviewProps) {
  const formatDate = (date: Date) => {
    return date.toLocaleString("en-US", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  };

  return (
    <div
      className={classNames(
        "rounded-lg border p-4",
        "bg-stone-50 dark:bg-stone-800",
        "border-stone-200 dark:border-stone-700",
      )}
    >
      {/* Pattern display */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <label className="text-sm font-medium text-stone-700 dark:text-stone-300">
            Generated Pattern
          </label>
          <span className="text-xs px-2 py-0.5 rounded bg-stone-200 dark:bg-stone-700 text-stone-600 dark:text-stone-400">
            {patternType}
          </span>
        </div>
        <div
          className={classNames(
            "px-3 py-2 rounded-md font-mono text-sm",
            "bg-white dark:bg-stone-900",
            "border border-stone-200 dark:border-stone-600",
            "text-stone-900 dark:text-stone-100",
            !pattern && "text-stone-400 dark:text-stone-500 italic",
          )}
        >
          {pattern || "Select characters to generate pattern..."}
        </div>
      </div>

      {/* Parse preview */}
      <div>
        <label className="text-sm font-medium text-stone-700 dark:text-stone-300 mb-2 block">
          Parse Preview
        </label>
        <div
          className={classNames(
            "px-3 py-2 rounded-md",
            "border",
            parseResult?.success
              ? [
                  "bg-emerald-50 dark:bg-emerald-900/20",
                  "border-emerald-200 dark:border-emerald-800",
                ]
              : parseResult?.error
                ? [
                    "bg-red-50 dark:bg-red-900/20",
                    "border-red-200 dark:border-red-800",
                  ]
                : [
                    "bg-white dark:bg-stone-900",
                    "border-stone-200 dark:border-stone-600",
                  ],
          )}
        >
          {isParsing ? (
            <span className="text-sm text-stone-500 dark:text-stone-400">
              Parsing...
            </span>
          ) : parseResult?.success && parseResult.date ? (
            <div className="flex items-center gap-2">
              <CheckIcon className="w-4 h-4 text-emerald-500" />
              <span className="text-sm font-medium text-emerald-700 dark:text-emerald-300">
                {formatDate(parseResult.date)}
              </span>
            </div>
          ) : parseResult?.error ? (
            <div className="flex items-start gap-2">
              <WarningIcon className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
              <span className="text-sm text-red-700 dark:text-red-300">
                {parseResult.error}
              </span>
            </div>
          ) : (
            <span className="text-sm text-stone-400 dark:text-stone-500 italic">
              Assign datetime components to see preview
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
