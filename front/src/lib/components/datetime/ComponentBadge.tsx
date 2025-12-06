"use client";

import classNames from "classnames";

import { CloseIcon } from "@/lib/components/icons";

import { COMPONENT_CONFIGS } from "./constants";
import type { DateTimeSelection } from "./types";

interface ComponentBadgeProps {
  /** The selection to display */
  selection: DateTimeSelection;
  /** Callback when remove button is clicked */
  onRemove: (id: string) => void;
  /** Whether the badge is disabled */
  disabled?: boolean;
}

/**
 * Displays a badge for a selected datetime component
 */
export default function ComponentBadge({
  selection,
  onRemove,
  disabled = false,
}: ComponentBadgeProps) {
  const config = COMPONENT_CONFIGS[selection.type];

  return (
    <div
      className={classNames(
        "inline-flex items-center gap-2 px-3 py-1.5 rounded-lg",
        "border transition-colors",
        config.bgColor,
        config.borderColor,
        config.textColor,
        disabled && "opacity-50",
      )}
    >
      <span className="font-medium text-sm">{config.label}</span>
      <span className="text-xs font-mono opacity-75">&quot;{selection.text}&quot;</span>
      <span className="text-xs opacity-60">
        [{selection.startIndex}-{selection.endIndex - 1}]
      </span>
      {!disabled && (
        <button
          type="button"
          onClick={() => onRemove(selection.id)}
          className={classNames(
            "ml-1 p-0.5 rounded-full transition-colors",
            "hover:bg-stone-900/10 dark:hover:bg-white/10",
            "focus:outline-none focus:ring-2 focus:ring-offset-1",
            `focus:ring-${config.color}-500`,
          )}
          aria-label={`Remove ${config.label} selection`}
        >
          <CloseIcon className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}
