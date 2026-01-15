"use client";

import classNames from "classnames";
import { useCallback, useMemo } from "react";

import { CheckIcon, CloseIcon, TimeIcon } from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import type { SpeciesFilterApplication } from "@/lib/types";

// ============================================================================
// Utility: Format relative time
// ============================================================================

function formatRelativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) {
    return "just now";
  } else if (diffMins < 60) {
    return `${diffMins} minute${diffMins === 1 ? "" : "s"} ago`;
  } else if (diffHours < 24) {
    return `${diffHours} hour${diffHours === 1 ? "" : "s"} ago`;
  } else if (diffDays < 7) {
    return `${diffDays} day${diffDays === 1 ? "" : "s"} ago`;
  } else {
    return date.toLocaleDateString();
  }
}

// ============================================================================
// Props Interface
// ============================================================================

interface FilterSummaryPanelProps {
  application: SpeciesFilterApplication;
  /** Callback to re-apply filter with different threshold */
  onReapply: (threshold: number) => void;
  /** Callback to view species results */
  onViewExcluded: () => void;
  /** Optional className for customization */
  className?: string;
}

// ============================================================================
// Pie Chart Component (Simple SVG)
// ============================================================================

function SimplePieChart({
  included,
  excluded,
}: {
  included: number;
  excluded: number;
}) {
  const total = included + excluded;
  if (total === 0) {
    return (
      <div className="w-32 h-32 rounded-full bg-stone-200 dark:bg-stone-700 flex items-center justify-center">
        <span className="text-xs text-stone-500 dark:text-stone-400">
          No data
        </span>
      </div>
    );
  }

  const includedPercent = (included / total) * 100;
  const excludedPercent = (excluded / total) * 100;

  // Calculate the stroke-dasharray and stroke-dashoffset for the pie segments
  const circumference = 2 * Math.PI * 45; // radius = 45
  const includedDash = (includedPercent / 100) * circumference;
  const excludedDash = (excludedPercent / 100) * circumference;

  return (
    <div className="relative w-32 h-32">
      <svg className="w-32 h-32 transform -rotate-90" viewBox="0 0 100 100">
        {/* Excluded (background) */}
        <circle
          cx="50"
          cy="50"
          r="45"
          fill="none"
          stroke="currentColor"
          strokeWidth="10"
          className="text-stone-300 dark:text-stone-600"
        />
        {/* Included (foreground) */}
        <circle
          cx="50"
          cy="50"
          r="45"
          fill="none"
          stroke="currentColor"
          strokeWidth="10"
          strokeLinecap="round"
          className="text-emerald-500 dark:text-emerald-400"
          style={{
            strokeDasharray: `${includedDash} ${circumference}`,
            strokeDashoffset: 0,
          }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-lg font-bold text-stone-900 dark:text-stone-100">
          {includedPercent.toFixed(0)}%
        </span>
        <span className="text-xs text-stone-500 dark:text-stone-400">
          pass rate
        </span>
      </div>
    </div>
  );
}

// ============================================================================
// Statistic Row Component
// ============================================================================

function StatRow({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: string | number;
  icon?: React.ReactNode;
  color?: "emerald" | "stone" | "default";
}) {
  const colorStyles = {
    emerald: "text-emerald-600 dark:text-emerald-400",
    stone: "text-stone-500 dark:text-stone-400",
    default: "text-stone-700 dark:text-stone-300",
  };

  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="flex items-center gap-2 text-sm text-stone-600 dark:text-stone-400">
        {icon}
        {label}
      </span>
      <span
        className={classNames("text-sm font-medium", colorStyles[color ?? "default"])}
      >
        {value}
      </span>
    </div>
  );
}

// ============================================================================
// Main Component
// ============================================================================

export default function FilterSummaryPanel({
  application,
  onReapply,
  onViewExcluded,
  className,
}: FilterSummaryPanelProps) {
  // Extract data from application
  const filterName = application.species_filter?.display_name ?? "Species Filter";
  const filterVersion = application.species_filter?.version ?? "";
  const threshold = application.threshold;
  const totalDetections = application.total_detections ?? 0;
  const includedCount = application.filtered_detections ?? 0;
  const excludedCount = application.excluded_detections ?? 0;
  const completedOn = application.completed_on;

  // Calculate pass rate
  const passRate =
    totalDetections > 0
      ? ((includedCount / totalDetections) * 100).toFixed(1)
      : "0.0";

  // Format applied time
  const appliedTimeText = useMemo(() => {
    if (!completedOn) return "Not completed";
    try {
      return formatRelativeTime(new Date(completedOn));
    } catch {
      return "Unknown";
    }
  }, [completedOn]);

  const handleReapply = useCallback(() => {
    onReapply(threshold);
  }, [threshold, onReapply]);

  return (
    <Card className={classNames("space-y-4", className)}>
      {/* Header */}
      <div>
        <h3 className="text-sm font-medium text-stone-900 dark:text-stone-100">
          Species Filter Applied
        </h3>
        <p className="text-lg font-semibold text-stone-900 dark:text-stone-100 mt-0.5">
          {filterName}
          {filterVersion && (
            <span className="text-stone-500 dark:text-stone-400 font-normal">
              {" "}
              v{filterVersion}
            </span>
          )}
        </p>
      </div>

      {/* Filter Info */}
      <div className="space-y-1 py-2 border-y border-stone-200 dark:border-stone-700">
        <StatRow
          label="Threshold"
          value={`${(threshold * 100).toFixed(0)}%`}
        />
        <StatRow
          label="Applied"
          value={appliedTimeText}
          icon={<TimeIcon className="w-4 h-4" />}
        />
      </div>

      {/* Pie Chart */}
      <div className="flex justify-center py-2">
        <SimplePieChart included={includedCount} excluded={excludedCount} />
      </div>

      {/* Legend */}
      <div className="flex justify-center gap-6 text-sm">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-emerald-500 dark:bg-emerald-400" />
          <span className="text-stone-600 dark:text-stone-400">
            Included: {includedCount.toLocaleString()} (
            {((includedCount / totalDetections) * 100 || 0).toFixed(0)}%)
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-stone-300 dark:bg-stone-600" />
          <span className="text-stone-600 dark:text-stone-400">
            Excluded: {excludedCount.toLocaleString()} (
            {((excludedCount / totalDetections) * 100 || 0).toFixed(0)}%)
          </span>
        </div>
      </div>

      {/* Statistics */}
      <div className="space-y-1 py-2 border-t border-stone-200 dark:border-stone-700">
        <h4 className="text-xs font-medium text-stone-500 dark:text-stone-400 uppercase tracking-wide mb-2">
          Statistics
        </h4>
        <StatRow label="Total Detections" value={totalDetections.toLocaleString()} />
        <StatRow
          label="Included"
          value={includedCount.toLocaleString()}
          icon={<CheckIcon className="w-4 h-4 text-emerald-500" />}
          color="emerald"
        />
        <StatRow
          label="Excluded"
          value={excludedCount.toLocaleString()}
          icon={<CloseIcon className="w-4 h-4 text-stone-400" />}
          color="stone"
        />
        <StatRow label="Pass Rate" value={`${passRate}%`} />
      </div>

      {/* View Species Button */}
      <div className="py-2 border-t border-stone-200 dark:border-stone-700">
        <Button
          mode="outline"
          variant="secondary"
          onClick={onViewExcluded}
          className="w-full text-sm"
        >
          View Species Results
        </Button>
      </div>

      {/* Re-apply Button */}
      <div className="pt-2 border-t border-stone-200 dark:border-stone-700">
        <Button
          mode="outline"
          variant="secondary"
          onClick={handleReapply}
          className="w-full text-sm"
        >
          Re-apply with different threshold
        </Button>
      </div>
    </Card>
  );
}
