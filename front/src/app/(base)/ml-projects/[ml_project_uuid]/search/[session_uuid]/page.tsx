"use client";

/**
 * Search Session detail / Active Learning labeling interface page.
 *
 * Displays search results with spectrograms and provides
 * multi-tag labeling functionality with keyboard shortcuts.
 * Supports bulk selection, active learning iterations, and export.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import toast from "react-hot-toast";
import {
  Play,
  CheckCircle,
  XCircle,
  HelpCircle,
  SkipForward,
  ArrowLeft,
  ArrowRight,
  Loader2,
  Tag,
  Music,
  Filter,
  ChevronLeft,
  RefreshCw,
  Download,
  Square,
  CheckSquare,
  MinusSquare,
  Save,
} from "lucide-react";

// Dynamically import Plotly to avoid SSR issues
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

import api from "@/app/api";
import { DEFAULT_SPECTROGRAM_PARAMETERS } from "@/lib/constants";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import ProgressBar from "@/lib/components/ui/ProgressBar";
import Link from "@/lib/components/ui/Link";
import ExportToAnnotationProjectDialog from "@/app/components/ml_projects/ExportToAnnotationProjectDialog";
import FinalizeSearchSessionDialog from "@/app/components/ml_projects/FinalizeSearchSessionDialog";

import type {
  SearchSession,
  SearchResult,
  SearchProgress,
  SearchSessionTargetTag,
  SearchResultLabelData,
  SampleType,
  RunIterationRequest,
  ScoreDistributionResponse,
  TagScoreDistribution,
  ClassifierType,
} from "@/lib/types";

type LabelFilterType =
  | "all"
  | "unlabeled"
  | "negative"
  | "uncertain"
  | "skipped"
  | `tag_${number}`;

// Helper function to determine result label status
function getResultLabelStatus(result: SearchResult): {
  type: "tagged" | "negative" | "uncertain" | "skipped" | "unlabeled";
  tagId?: number;
  tagIds?: number[];
} {
  // Check for multiple tags (future support)
  const assignedTagIds = (result as any).assigned_tag_ids as number[] | undefined;
  if (assignedTagIds && assignedTagIds.length > 0) {
    return { type: "tagged", tagIds: assignedTagIds };
  }
  // Fallback to single tag
  if (result.assigned_tag_id) return { type: "tagged", tagId: result.assigned_tag_id };
  if (result.is_negative) return { type: "negative" };
  if (result.is_uncertain) return { type: "uncertain" };
  if (result.is_skipped) return { type: "skipped" };
  return { type: "unlabeled" };
}

// Generate a color from tag_id if no color is provided
function generateTagColor(tagId: number): string {
  const colors = [
    "#10b981", // emerald-500
    "#3b82f6", // blue-500
    "#8b5cf6", // violet-500
    "#f59e0b", // amber-500
    "#ec4899", // pink-500
    "#06b6d4", // cyan-500
    "#84cc16", // lime-500
    "#f97316", // orange-500
    "#6366f1", // indigo-500
  ];
  return colors[tagId % colors.length];
}

// Format score display with percentile and raw value
function formatScoreDisplay(result: SearchResult): {
  percentileText: string;
  rawValueText: string;
  compactText: string;
} {
  const percentile = result.score_percentile;
  const rawScore = result.raw_score;
  const metric = result.result_distance_metric;

  // Percentile text: "Top X%"
  const percentileText = percentile != null
    ? `Top ${(100 - percentile).toFixed(0)}%`
    : "";

  // Raw value text based on metric
  let rawValueText = "";
  if (rawScore != null) {
    if (metric === "euclidean") {
      rawValueText = `Euclidean: ${rawScore.toFixed(3)}`;
    } else {
      rawValueText = `Cosine: ${rawScore.toFixed(3)}`;
    }
  }

  // Compact text for badges: "Top X% (Cos: 0.85)" or "Top X% (Euc: 0.42)"
  let compactText = "";
  if (percentile != null && rawScore != null) {
    const metricShort = metric === "euclidean" ? "Euc" : "Cos";
    compactText = `Top ${(100 - percentile).toFixed(0)}% (${metricShort}: ${rawScore.toFixed(2)})`;
  } else if (percentile != null) {
    compactText = `Top ${(100 - percentile).toFixed(0)}%`;
  } else {
    // Fallback to old-style percentage
    compactText = `${(result.similarity * 100).toFixed(1)}%`;
  }

  return { percentileText, rawValueText, compactText };
}

// Label status colors
const LABEL_STATUS_COLORS: Record<string, string> = {
  unlabeled: "bg-stone-100 text-stone-600 dark:bg-stone-700 dark:text-stone-400",
  negative: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  uncertain: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
  skipped: "bg-stone-200 text-stone-500 dark:bg-stone-600 dark:text-stone-400",
  tagged: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
};

const LABEL_STATUS_ICONS: Record<string, React.ReactNode> = {
  unlabeled: null,
  negative: <XCircle className="w-4 h-4" />,
  uncertain: <HelpCircle className="w-4 h-4" />,
  skipped: <SkipForward className="w-4 h-4" />,
  tagged: <CheckCircle className="w-4 h-4" />,
};

// Sample type badge colors
const SAMPLE_TYPE_COLORS: Record<SampleType, string> = {
  easy_positive: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  boundary: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  others: "bg-stone-100 text-stone-600 dark:bg-stone-700 dark:text-stone-400",
  active_learning: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
};

const SAMPLE_TYPE_LABELS: Record<SampleType, string> = {
  easy_positive: "Easy Positive",
  boundary: "Boundary",
  others: "Others",
  active_learning: "Active Learning",
};

function TagLabelButton({
  targetTag,
  shortcut,
  onClick,
  active,
  disabled,
}: {
  targetTag: SearchSessionTargetTag;
  shortcut: string;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  const color = generateTagColor(targetTag.tag_id);
  const displayName =
    targetTag.tag.vernacular_name || targetTag.tag.canonical_name || targetTag.tag.value;

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors border-2 ${
        active
          ? "ring-2 ring-offset-2 ring-opacity-50 shadow-md"
          : "border-transparent hover:border-opacity-50"
      } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
      style={{
        backgroundColor: active ? `${color}40` : `${color}10`,
        borderColor: active ? color : "transparent",
        color: active ? color : undefined,
      }}
    >
      <span
        className={`w-3 h-3 rounded-full ${active ? "ring-2 ring-white" : ""}`}
        style={{ backgroundColor: color }}
      />
      <span className="font-medium text-sm truncate max-w-[120px]">
        {shortcut}: {displayName}
      </span>
    </button>
  );
}

function SpecialLabelButton({
  label,
  shortcut,
  onClick,
  active,
  disabled,
  icon,
}: {
  label: string;
  shortcut: string;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  icon: React.ReactNode;
}) {
  const colors: Record<string, string> = {
    Negative:
      "hover:bg-red-100 dark:hover:bg-red-900/30 hover:text-red-700 dark:hover:text-red-400",
    Uncertain:
      "hover:bg-yellow-100 dark:hover:bg-yellow-900/30 hover:text-yellow-700 dark:hover:text-yellow-400",
    Skip: "hover:bg-stone-200 dark:hover:bg-stone-600 hover:text-stone-600 dark:hover:text-stone-300",
  };

  const activeColors: Record<string, string> = {
    Negative: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 ring-2 ring-red-500",
    Uncertain:
      "bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 ring-2 ring-yellow-500",
    Skip: "bg-stone-200 dark:bg-stone-600 text-stone-600 dark:text-stone-300 ring-2 ring-stone-500",
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
        active ? activeColors[label] : colors[label]
      } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
    >
      {icon}
      <span className="font-medium">{label}</span>
      <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">{shortcut}</kbd>
    </button>
  );
}

function ResultCard({
  result,
  isSelected,
  isChecked,
  onSelect,
  onCheckToggle,
  targetTags,
  showCheckbox,
}: {
  result: SearchResult;
  isSelected: boolean;
  isChecked: boolean;
  onSelect: () => void;
  onCheckToggle: () => void;
  targetTags: SearchSessionTargetTag[];
  showCheckbox: boolean;
}) {
  const labelStatus = getResultLabelStatus(result);
  const assignedTag = targetTags.find((t) => t.tag_id === labelStatus.tagId);
  const tagColor = assignedTag
    ? generateTagColor(assignedTag.tag_id)
    : labelStatus.tagId
      ? generateTagColor(labelStatus.tagId)
      : undefined;

  return (
    <Card
      className={`cursor-pointer transition-all relative ${
        isSelected ? "ring-2 ring-emerald-500 border-emerald-500" : "hover:border-emerald-500/50"
      }`}
      onClick={onSelect}
    >
      {/* Checkbox for bulk selection */}
      {showCheckbox && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onCheckToggle();
          }}
          className="absolute top-2 left-2 z-10 p-1 rounded bg-white/80 dark:bg-stone-900/80 hover:bg-white dark:hover:bg-stone-900"
        >
          {isChecked ? (
            <CheckSquare className="w-5 h-5 text-emerald-500" />
          ) : (
            <Square className="w-5 h-5 text-stone-400" />
          )}
        </button>
      )}

      {/* Spectrogram */}
      <div className="aspect-[2/1] bg-stone-100 dark:bg-stone-800 rounded-lg mb-2 flex items-center justify-center relative overflow-hidden group">
        <img
          src={api.spectrograms.getUrl({
            uuid: result.clip.recording.uuid,
            interval: { min: result.clip.start_time, max: result.clip.end_time },
            ...DEFAULT_SPECTROGRAM_PARAMETERS,
          })}
          alt="Spectrogram"
          className="absolute inset-0 w-full h-full object-cover"
        />
        {/* Play button overlay - only visible on hover */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            // Select this result first
            onSelect();
            // Then play audio
            const audio = new Audio(
              api.audio.getStreamUrl({
                recording: result.clip.recording,
                startTime: result.clip.start_time,
                endTime: result.clip.end_time,
              })
            );
            audio.play();
          }}
          className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-10 h-10 flex items-center justify-center bg-black/50 rounded-full opacity-0 group-hover:opacity-100 transition-opacity hover:bg-black/70"
        >
          <Play className="w-5 h-5 text-white" />
        </button>

        {/* Score badge with source tag - shows which tag this sample is similar to */}
        {result.source_tag_id && (
          <span
            className="absolute top-2 right-2 px-2 py-0.5 text-xs rounded-full flex items-center gap-1"
            style={{
              backgroundColor: `${generateTagColor(result.source_tag_id)}20`,
              color: generateTagColor(result.source_tag_id),
            }}
          >
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: generateTagColor(result.source_tag_id) }}
            />
            {(() => {
              const sourceTag = targetTags.find((t) => t.tag_id === result.source_tag_id);
              const tagName = sourceTag
                ? sourceTag.tag.vernacular_name || sourceTag.tag.canonical_name || sourceTag.tag.value
                : `Tag ${result.source_tag_id}`;
              const { compactText } = formatScoreDisplay(result);

              if (result.sample_type === "active_learning" && result.model_score != null) {
                // AL sample: show tag name with "?" and model score
                return `${tagName}? ${(result.model_score * 100).toFixed(0)}%`;
              } else {
                // Initial sample: show tag name and percentile/raw score
                return `${tagName}: ${compactText}`;
              }
            })()}
          </span>
        )}
        {/* Fallback for samples without source_tag_id (e.g., "others" samples) */}
        {!result.source_tag_id && (
          <span className="absolute top-2 right-2 px-2 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 text-stone-600 dark:text-stone-300 rounded-full">
            {result.sample_type === "others" ? "Random" : formatScoreDisplay(result).compactText}
          </span>
        )}

        {/* Iteration badge */}
        {result.iteration_added != null && result.iteration_added > 0 && (
          <span className="absolute bottom-2 left-2 px-2 py-0.5 text-xs bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 rounded-full">
            Iter {result.iteration_added}
          </span>
        )}

        {/* Sample type badge */}
        {result.sample_type && (
          <span
            className={`absolute bottom-2 right-2 px-2 py-0.5 text-xs rounded-full ${SAMPLE_TYPE_COLORS[result.sample_type]}`}
          >
            {SAMPLE_TYPE_LABELS[result.sample_type]}
          </span>
        )}
      </div>

      {/* Label badge */}
      <div className="flex items-center justify-between">
        {labelStatus.type === "tagged" ? (
          <div className="flex items-center gap-1 flex-wrap">
            {/* Multiple tags support */}
            {labelStatus.tagIds && labelStatus.tagIds.length > 0 ? (
              labelStatus.tagIds.map((tagId) => {
                const tag = targetTags.find((t) => t.tag_id === tagId);
                const color = generateTagColor(tagId);
                const displayName = tag
                  ? tag.tag.vernacular_name || tag.tag.canonical_name || tag.tag.value
                  : `Tag ${tagId}`;
                return (
                  <span
                    key={tagId}
                    className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full"
                    style={{
                      backgroundColor: `${color}20`,
                      color: color,
                    }}
                  >
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                    {displayName}
                  </span>
                );
              })
            ) : (
              /* Single tag fallback */
              assignedTag && (
                <span
                  className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full"
                  style={{
                    backgroundColor: `${tagColor}20`,
                    color: tagColor,
                  }}
                >
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: tagColor }} />
                  {assignedTag.tag.vernacular_name ||
                    assignedTag.tag.canonical_name ||
                    assignedTag.tag.value}
                </span>
              )
            )}
          </div>
        ) : (
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${LABEL_STATUS_COLORS[labelStatus.type]}`}
          >
            {LABEL_STATUS_ICONS[labelStatus.type]}
            {labelStatus.type.charAt(0).toUpperCase() + labelStatus.type.slice(1)}
          </span>
        )}
        <span className="text-xs text-stone-500">#{result.rank}</span>
      </div>
    </Card>
  );
}

function KeyboardShortcutsHelp({ targetTags }: { targetTags: SearchSessionTargetTag[] }) {
  return (
    <Card className="p-4">
      <h4 className="font-medium text-sm mb-2">Keyboard Shortcuts</h4>
      <div className="space-y-1 text-sm text-stone-600 dark:text-stone-400">
        {targetTags.map((targetTag) => {
          if (targetTag.shortcut_key > 9) return null;
          const displayName =
            targetTag.tag.vernacular_name || targetTag.tag.canonical_name || targetTag.tag.value;
          return (
            <div key={targetTag.tag_id} className="flex justify-between">
              <span className="truncate mr-2">{displayName}</span>
              <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">
                {targetTag.shortcut_key}
              </kbd>
            </div>
          );
        })}
        <div className="border-t border-stone-200 dark:border-stone-700 mt-2 pt-2" />
        <div className="flex justify-between">
          <span>Negative</span>
          <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">N</kbd>
        </div>
        <div className="flex justify-between">
          <span>Uncertain</span>
          <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">U</kbd>
        </div>
        <div className="flex justify-between">
          <span>Skip</span>
          <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">S</kbd>
        </div>
        <div className="border-t border-stone-200 dark:border-stone-700 mt-2 pt-2" />
        <div className="flex justify-between">
          <span>Play Audio</span>
          <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">
            Space
          </kbd>
        </div>
        <div className="flex justify-between">
          <span>Previous</span>
          <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">
            Left Arrow
          </kbd>
        </div>
        <div className="flex justify-between">
          <span>Next</span>
          <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">
            Right Arrow
          </kbd>
        </div>
      </div>
    </Card>
  );
}

function ScoreHistogramChart({
  distributions,
  targetTags,
}: {
  distributions: TagScoreDistribution[];
  targetTags: SearchSessionTargetTag[];
}) {
  if (!distributions || distributions.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-stone-500">
        No distribution data available yet
      </div>
    );
  }

  // Group distributions by tag_id
  const distributionsByTag = distributions.reduce((acc, dist) => {
    if (!acc[dist.tag_id]) {
      acc[dist.tag_id] = [];
    }
    acc[dist.tag_id].push(dist);
    return acc;
  }, {} as Record<number, TagScoreDistribution[]>);

  // Iteration colors
  const iterationColors = [
    "#3b82f6", // blue
    "#10b981", // emerald
    "#f59e0b", // amber
    "#8b5cf6", // violet
    "#ec4899", // pink
    "#06b6d4", // cyan
    "#84cc16", // lime
    "#f97316", // orange
  ];

  // Create traces for each tag and iteration
  const traces: any[] = [];
  const annotations: any[] = [];

  Object.entries(distributionsByTag).forEach(([tagIdStr, tagDists], tagIndex) => {
    const tagId = parseInt(tagIdStr);
    const targetTag = targetTags.find((t) => t.tag_id === tagId);
    const tagName = targetTag
      ? targetTag.tag.vernacular_name || targetTag.tag.canonical_name || targetTag.tag.value
      : `Tag ${tagId}`;

    // Sort by iteration
    tagDists.sort((a, b) => a.iteration - b.iteration);

    tagDists.forEach((dist, iterIdx) => {
      const color = iterationColors[dist.iteration % iterationColors.length];

      // Create bin centers from bin_edges for x-axis
      const binCenters = dist.bin_edges.slice(0, -1).map((edge, i) => {
        return (edge + dist.bin_edges[i + 1]) / 2;
      });

      traces.push({
        x: binCenters,
        y: dist.bin_counts,
        type: "bar",
        name: `Iter ${dist.iteration}`,
        marker: { color: color, opacity: 0.7 },
        xaxis: `x${tagIndex + 1}`,
        yaxis: `y${tagIndex + 1}`,
        legendgroup: `iter${dist.iteration}`,
        showlegend: tagIndex === 0, // Only show legend for first tag
      });
    });

    // Add annotation for tag name
    annotations.push({
      text: `<b>${tagName}</b>`,
      xref: `x${tagIndex + 1} domain`,
      yref: `y${tagIndex + 1} domain`,
      x: 0.5,
      y: 1.05,
      xanchor: "center",
      yanchor: "bottom",
      showarrow: false,
      font: { size: 12 },
    });
  });

  const numTags = Object.keys(distributionsByTag).length;
  const subplotHeight = 1 / numTags;

  // Create layout with subplots
  const layout: any = {
    height: Math.max(350, numTags * 250),
    showlegend: true,
    legend: {
      orientation: "h",
      yanchor: "bottom",
      y: 1.08,
      xanchor: "center",
      x: 0.5,
    },
    annotations,
    margin: { t: 80, b: 50, l: 60, r: 20 },
    plot_bgcolor: "rgba(0,0,0,0)",
    paper_bgcolor: "rgba(0,0,0,0)",
  };

  // Configure subplots with more spacing
  const gapBetweenSubplots = 0.15; // 15% gap between subplots
  const availableHeight = 1 - gapBetweenSubplots * (numTags - 1);
  const plotHeight = availableHeight / numTags;

  Object.keys(distributionsByTag).forEach((tagIdStr, idx) => {
    const axisNum = idx + 1;
    const yStart = 1 - (idx + 1) * plotHeight - idx * gapBetweenSubplots;
    const yEnd = 1 - idx * plotHeight - idx * gapBetweenSubplots;
    const yDomain = [yStart, yEnd];

    layout[`xaxis${axisNum === 1 ? "" : axisNum}`] = {
      domain: [0, 1],
      anchor: `y${axisNum}`,
      title: idx === numTags - 1 ? "Model Score" : "",
      range: [0, 1],
    };

    layout[`yaxis${axisNum === 1 ? "" : axisNum}`] = {
      domain: yDomain,
      anchor: `x${axisNum}`,
      title: "Count (log)",
      type: "log",
    };
  });

  return (
    <div className="w-full">
      <Plot
        data={traces}
        layout={layout}
        config={{ responsive: true, displayModeBar: false }}
        className="w-full"
      />
    </div>
  );
}

function BulkActionBar({
  selectedCount,
  targetTags,
  onBulkLabel,
  onClearSelection,
  isLabeling,
}: {
  selectedCount: number;
  targetTags: SearchSessionTargetTag[];
  onBulkLabel: (labelData: SearchResultLabelData) => void;
  onClearSelection: () => void;
  isLabeling: boolean;
}) {
  return (
    <div className="fixed bottom-4 left-1/2 transform -translate-x-1/2 z-50">
      <Card className="flex items-center gap-4 px-6 py-4 shadow-xl border-emerald-500">
        <div className="flex items-center gap-2 pr-4 border-r border-stone-200 dark:border-stone-700">
          <CheckSquare className="w-5 h-5 text-emerald-500" />
          <span className="font-medium">{selectedCount} selected</span>
        </div>

        {/* Tag buttons */}
        <div className="flex items-center gap-2 flex-wrap">
          {targetTags
            .filter((t) => t.shortcut_key <= 9)
            .map((targetTag) => {
              const color = generateTagColor(targetTag.tag_id);
              return (
                <button
                  key={targetTag.tag_id}
                  onClick={() => onBulkLabel({ assigned_tag_id: targetTag.tag_id })}
                  disabled={isLabeling}
                  className="flex items-center gap-1 px-2 py-1 rounded text-sm font-medium transition-colors hover:opacity-80 disabled:opacity-50"
                  style={{
                    backgroundColor: `${color}20`,
                    color: color,
                  }}
                >
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                  {targetTag.shortcut_key}
                </button>
              );
            })}
        </div>

        {/* Special labels */}
        <div className="flex items-center gap-2 pl-4 border-l border-stone-200 dark:border-stone-700">
          <button
            onClick={() => onBulkLabel({ is_negative: true })}
            disabled={isLabeling}
            className="px-2 py-1 rounded text-sm font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 disabled:opacity-50"
          >
            N
          </button>
          <button
            onClick={() => onBulkLabel({ is_uncertain: true })}
            disabled={isLabeling}
            className="px-2 py-1 rounded text-sm font-medium bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 hover:bg-yellow-200 dark:hover:bg-yellow-900/50 disabled:opacity-50"
          >
            U
          </button>
          <button
            onClick={() => onBulkLabel({ is_skipped: true })}
            disabled={isLabeling}
            className="px-2 py-1 rounded text-sm font-medium bg-stone-200 dark:bg-stone-600 text-stone-600 dark:text-stone-300 hover:bg-stone-300 dark:hover:bg-stone-500 disabled:opacity-50"
          >
            S
          </button>
        </div>

        <button
          onClick={onClearSelection}
          className="ml-2 px-3 py-1 rounded text-sm text-stone-500 hover:text-stone-700 dark:hover:text-stone-300 hover:bg-stone-100 dark:hover:bg-stone-700"
        >
          Clear
        </button>
      </Card>
    </div>
  );
}

export default function SearchSessionDetailPage() {
  const params = useParams();
  const mlProjectUuid = params.ml_project_uuid as string;
  const sessionUuid = params.session_uuid as string;
  const queryClient = useQueryClient();

  const [selectedIndex, setSelectedIndex] = useState(0);
  const [labelFilter, setLabelFilter] = useState<LabelFilterType>("all");
  const [iterationFilter, setIterationFilter] = useState<number | null>(null);
  const [page, setPage] = useState(0);
  const pageSize = 12;

  // Auto-play state
  const [autoPlay, setAutoPlay] = useState(true);
  const [shouldAutoPlay, setShouldAutoPlay] = useState(false);

  // Bulk selection state
  const [selectedResults, setSelectedResults] = useState<Set<string>>(new Set());
  const [showCheckboxes, setShowCheckboxes] = useState(false);

  // Export dialog state
  const [showExportDialog, setShowExportDialog] = useState(false);

  // Finalize dialog state
  const [showFinalizeDialog, setShowFinalizeDialog] = useState(false);

  // Iteration dialog state
  const [showIterationDialog, setShowIterationDialog] = useState(false);
  const [iterationParams, setIterationParams] = useState<RunIterationRequest>({
    uncertainty_low: 0.25,
    uncertainty_high: 0.75,
    samples_per_iteration: 20,
    classifier_type: "logistic_regression",
  });
  const [selectedTagsForIteration, setSelectedTagsForIteration] = useState<Set<number>>(new Set());

  // Fetch session
  const {
    data: session,
    isLoading: sessionLoading,
    refetch: refetchSession,
  } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_session", sessionUuid],
    queryFn: () => api.searchSessions.get(mlProjectUuid, sessionUuid),
    enabled: !!mlProjectUuid && !!sessionUuid,
  });

  const targetTags = session?.target_tags || [];

  // Build filter params for API
  const filterParams = useMemo(() => {
    const params: Record<string, any> = {};

    // Iteration filter
    if (iterationFilter !== null) {
      params.iteration_added = iterationFilter;
    }

    // Label filter
    if (labelFilter === "unlabeled") {
      params.is_labeled = false;
    } else if (labelFilter === "negative") {
      params.is_negative = true;
    } else if (labelFilter === "uncertain") {
      params.is_uncertain = true;
    } else if (labelFilter === "skipped") {
      params.is_skipped = true;
    } else if (labelFilter.startsWith("tag_")) {
      const tagId = parseInt(labelFilter.replace("tag_", ""));
      params.assigned_tag_id = tagId;
    }

    return params;
  }, [labelFilter, iterationFilter]);

  // Fetch results
  const {
    data: resultsData,
    isLoading: resultsLoading,
    refetch: refetchResults,
  } = useQuery({
    queryKey: [
      "ml_project",
      mlProjectUuid,
      "search_session",
      sessionUuid,
      "results",
      filterParams,
      page,
    ],
    queryFn: () =>
      api.searchSessions.getResults(mlProjectUuid, sessionUuid, {
        limit: pageSize,
        offset: page * pageSize,
        ...filterParams,
      }),
    enabled: !!session?.is_search_complete,
  });

  // Fetch progress
  const { data: progress, refetch: refetchProgress } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_session", sessionUuid, "progress"],
    queryFn: () => api.searchSessions.getProgress(mlProjectUuid, sessionUuid),
    enabled: !!session?.is_search_complete,
    refetchInterval: session?.is_search_complete ? 5000 : false,
  });

  // Fetch score distribution for iteration dialog
  const {
    data: scoreDistribution,
    isLoading: scoreLoading,
    refetch: refetchScoreDistribution,
  } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_session", sessionUuid, "score_distribution"],
    queryFn: () => api.searchSessions.getScoreDistribution(mlProjectUuid, sessionUuid),
    enabled: showIterationDialog && !!session && session.current_iteration > 0,
  });

  const results = resultsData?.items || [];
  const totalResults = resultsData?.total || 0;
  const numPages = Math.ceil(totalResults / pageSize);

  const selectedResult = results[selectedIndex];

  // Execute search mutation
  const executeMutation = useMutation({
    mutationFn: () => api.searchSessions.execute(mlProjectUuid, sessionUuid),
    onSuccess: () => {
      toast.success("Search started");
      refetchSession();
    },
    onError: () => {
      toast.error("Failed to execute search");
    },
  });

  // Label result mutation with optimistic update
  const resultsQueryKey = [
    "ml_project",
    mlProjectUuid,
    "search_session",
    sessionUuid,
    "results",
    filterParams,
    page,
  ];

  const labelMutation = useMutation({
    mutationFn: ({
      resultUuid,
      labelData,
    }: {
      resultUuid: string;
      labelData: SearchResultLabelData;
    }) => {
      return api.searchSessions.labelResult(mlProjectUuid, sessionUuid, resultUuid, labelData);
    },
    onMutate: async ({ resultUuid, labelData }) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: resultsQueryKey });

      // Snapshot the previous value
      const previousData = queryClient.getQueryData(resultsQueryKey);

      // Optimistically update the cache immediately
      queryClient.setQueryData(resultsQueryKey, (old: typeof resultsData) => {
        if (!old) return old;
        return {
          ...old,
          items: old.items.map((r: SearchResult) =>
            r.uuid === resultUuid
              ? {
                  ...r,
                  assigned_tag_id: labelData.assigned_tag_id ?? null,
                  assigned_tag_ids: (labelData as any).assigned_tag_ids ?? undefined,
                  is_negative: labelData.is_negative ?? false,
                  is_uncertain: labelData.is_uncertain ?? false,
                  is_skipped: labelData.is_skipped ?? false,
                }
              : r
          ),
        };
      });

      // Only auto-advance for status labels (negative/uncertain/skipped), not for tag assignments
      // This allows users to assign multiple tags without auto-navigation
      const isStatusLabel =
        labelData.is_negative !== undefined ||
        labelData.is_uncertain !== undefined ||
        labelData.is_skipped !== undefined;

      if (isStatusLabel) {
        // Move to next result immediately
        if (selectedIndex < results.length - 1) {
          setSelectedIndex(selectedIndex + 1);
          // Trigger auto-play for next result
          if (autoPlay) {
            setShouldAutoPlay(true);
          }
        } else if (page < numPages - 1) {
          setPage(page + 1);
          setSelectedIndex(0);
          // Trigger auto-play for next result
          if (autoPlay) {
            setShouldAutoPlay(true);
          }
        }
      }

      return { previousData };
    },
    onError: (_error, _variables, context) => {
      // Rollback on error
      if (context?.previousData) {
        queryClient.setQueryData(resultsQueryKey, context.previousData);
      }
      toast.error("Failed to label result");
    },
    onSettled: () => {
      // Refresh progress in background (don't refetch results)
      refetchProgress();
    },
  });

  // Bulk label mutation
  const bulkLabelMutation = useMutation({
    mutationFn: (labelData: SearchResultLabelData) => {
      const resultUuids = Array.from(selectedResults);
      return api.searchSessions.bulkLabel(mlProjectUuid, sessionUuid, {
        result_uuids: resultUuids,
        label_data: labelData,
      });
    },
    onSuccess: (data) => {
      toast.success(`Labeled ${data.updated_count} results`);
      setSelectedResults(new Set());
      refetchResults();
      refetchProgress();
    },
    onError: () => {
      toast.error("Failed to bulk label results");
    },
  });

  // Run iteration mutation (for active learning)
  const runIterationMutation = useMutation({
    mutationFn: (params: RunIterationRequest) =>
      api.searchSessions.runIteration(mlProjectUuid, sessionUuid, params),
    onSuccess: (data) => {
      const newSamples = data.total_results - (session?.total_results ?? 0);
      toast.success(`Added ${newSamples} new samples`);
      setShowIterationDialog(false);
      // Set filter to show only the new iteration
      setIterationFilter(data.current_iteration);
      setPage(0);
      setSelectedIndex(0);
      refetchSession();
      refetchResults();
      refetchProgress();
    },
    onError: () => {
      toast.error("Failed to run iteration");
    },
  });

  // Handle single result label - no waiting for server response
  const handleLabel = useCallback(
    (labelData: SearchResultLabelData) => {
      if (!selectedResult) return;
      // Don't check isPending - allow rapid labeling
      labelMutation.mutate({ resultUuid: selectedResult.uuid, labelData });
    },
    [selectedResult, labelMutation]
  );

  // Handle tag label (keys 1-9) - Toggle mode
  const handleTagLabel = useCallback(
    (shortcutKey: number) => {
      if (!selectedResult) return;
      const targetTag = targetTags.find((t) => t.shortcut_key === shortcutKey);
      if (!targetTag) return;

      // Get current assigned tag IDs (support both single and multiple)
      const currentTagIds = (selectedResult as any).assigned_tag_ids as number[] | undefined;
      const currentSingleTag = selectedResult.assigned_tag_id;

      let newTagIds: number[];
      if (currentTagIds && currentTagIds.length > 0) {
        // Multiple tags mode: toggle the tag
        if (currentTagIds.includes(targetTag.tag_id)) {
          newTagIds = currentTagIds.filter((id) => id !== targetTag.tag_id);
        } else {
          newTagIds = [...currentTagIds, targetTag.tag_id];
        }
      } else if (currentSingleTag) {
        // Convert single tag to multiple and toggle
        if (currentSingleTag === targetTag.tag_id) {
          newTagIds = []; // Remove the only tag
        } else {
          newTagIds = [currentSingleTag, targetTag.tag_id];
        }
      } else {
        // No tags assigned yet
        newTagIds = [targetTag.tag_id];
      }

      // Send both assigned_tag_ids and assigned_tag_id for backward compatibility
      // Backend should accept assigned_tag_ids in the future
      const labelData: any = {
        assigned_tag_ids: newTagIds,
        // For backward compatibility: send single tag if only one is selected
        assigned_tag_id: newTagIds.length === 1 ? newTagIds[0] : null,
      };

      handleLabel(labelData);
    },
    [selectedResult, targetTags, handleLabel]
  );

  // Handle navigation
  const handlePrevious = useCallback(() => {
    if (selectedIndex > 0) {
      setSelectedIndex(selectedIndex - 1);
    } else if (page > 0) {
      setPage(page - 1);
      setSelectedIndex(pageSize - 1);
    }
  }, [selectedIndex, page, pageSize]);

  const handleNext = useCallback(() => {
    if (selectedIndex < results.length - 1) {
      setSelectedIndex(selectedIndex + 1);
    } else if (page < numPages - 1) {
      setPage(page + 1);
      setSelectedIndex(0);
    }
  }, [selectedIndex, results.length, page, numPages]);

  // Bulk selection handlers
  const handleCheckToggle = useCallback((uuid: string) => {
    setSelectedResults((prev) => {
      const next = new Set(prev);
      if (next.has(uuid)) {
        next.delete(uuid);
      } else {
        next.add(uuid);
      }
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    const allUuids = new Set(results.map((r) => r.uuid));
    setSelectedResults(allUuids);
  }, [results]);

  const handleDeselectAll = useCallback(() => {
    setSelectedResults(new Set());
  }, []);

  // Initialize selectedTagsForIteration with all target tags
  useEffect(() => {
    if (targetTags.length > 0 && selectedTagsForIteration.size === 0) {
      setSelectedTagsForIteration(new Set(targetTags.map((t) => t.tag_id)));
    }
  }, [targetTags, selectedTagsForIteration.size]);

  // Auto-play audio after labeling
  useEffect(() => {
    if (shouldAutoPlay && selectedResult && autoPlay) {
      // Play audio for the selected result
      const audio = new Audio(
        api.audio.getStreamUrl({
          recording: selectedResult.clip.recording,
          startTime: selectedResult.clip.start_time,
          endTime: selectedResult.clip.end_time,
        })
      );
      audio.play().catch((error) => {
        console.error("Auto-play failed:", error);
      });

      // Reset the flag
      setShouldAutoPlay(false);
    }
  }, [selectedResult, shouldAutoPlay, autoPlay]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

      // Space key to play audio
      if (e.key === " ") {
        e.preventDefault(); // Prevent page scroll
        if (selectedResult) {
          const audio = new Audio(
            api.audio.getStreamUrl({
              recording: selectedResult.clip.recording,
              startTime: selectedResult.clip.start_time,
              endTime: selectedResult.clip.end_time,
            })
          );
          audio.play().catch((error) => {
            console.error("Failed to play audio:", error);
          });
        }
        return;
      }

      // Number keys 1-9 for tags
      if (e.key >= "1" && e.key <= "9") {
        const shortcutKey = parseInt(e.key);
        handleTagLabel(shortcutKey);
        return;
      }

      switch (e.key.toLowerCase()) {
        case "n":
          handleLabel({ is_negative: true });
          break;
        case "u":
          handleLabel({ is_uncertain: true });
          break;
        case "s":
          handleLabel({ is_skipped: true });
          break;
        case "arrowleft":
          handlePrevious();
          break;
        case "arrowright":
          handleNext();
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleLabel, handleTagLabel, handlePrevious, handleNext, selectedResult]);

  if (sessionLoading) {
    return <Loading />;
  }

  if (!session) {
    return null;
  }

  const currentLabelStatus = selectedResult ? getResultLabelStatus(selectedResult) : null;
  const currentAssignedTag = currentLabelStatus?.tagId
    ? targetTags.find((t) => t.tag_id === currentLabelStatus.tagId)
    : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href={`/ml-projects/${mlProjectUuid}/search`}>
            <Button variant="secondary" mode="text">
              <ChevronLeft className="w-4 h-4 mr-1" />
              Back to Sessions
            </Button>
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-semibold text-stone-900 dark:text-stone-100">
                {session.name}
              </h2>
              {session.current_iteration > 0 && (
                <span className="px-2 py-0.5 text-xs bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 rounded-full">
                  Iteration {session.current_iteration}
                </span>
              )}
            </div>
            {targetTags.length > 0 && (
              <div className="flex items-center gap-2 mt-1 flex-wrap">
                <Tag className="w-4 h-4 text-stone-400" />
                {targetTags.map((targetTag) => {
                  const color = generateTagColor(targetTag.tag_id);
                  return (
                    <span
                      key={targetTag.tag_id}
                      className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full"
                      style={{
                        backgroundColor: `${color}20`,
                        color: color,
                      }}
                    >
                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                      {targetTag.tag.vernacular_name ||
                        targetTag.tag.canonical_name ||
                        targetTag.tag.value}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Run Next Iteration button */}
          {session.is_search_complete && (
            <Button
              variant="secondary"
              onClick={() => setShowIterationDialog(true)}
              disabled={runIterationMutation.isPending}
            >
              {runIterationMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4 mr-2" />
              )}
              Run Next Iteration
            </Button>
          )}

          {/* Export button */}
          {session.is_search_complete && (
            <Button variant="secondary" onClick={() => setShowExportDialog(true)}>
              <Download className="w-4 h-4 mr-2" />
              Export
            </Button>
          )}

          {/* Finalize button */}
          {session.is_search_complete && (
            <Button variant="primary" onClick={() => setShowFinalizeDialog(true)}>
              <Save className="w-4 h-4 mr-2" />
              Finalize & Save
            </Button>
          )}
        </div>
      </div>

      {/* Not executed yet */}
      {!session.is_search_complete && (
        <Card className="p-8 text-center">
          <Play className="w-12 h-12 mx-auto mb-4 text-stone-400" />
          <h3 className="text-lg font-medium">Search Not Executed</h3>
          <p className="text-sm text-stone-500 dark:text-stone-400 mt-2 mb-4">
            Execute the search to find similar sounds in the dataset based on your reference sounds.
          </p>
          <Button
            variant="primary"
            onClick={() => executeMutation.mutate()}
            disabled={executeMutation.isPending}
          >
            {executeMutation.isPending ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Executing...
              </>
            ) : (
              <>
                <Play className="w-4 h-4 mr-2" />
                Execute Search
              </>
            )}
          </Button>
        </Card>
      )}

      {/* Search executed - show results */}
      {session.is_search_complete && (
        <>
          {/* Progress */}
          {progress && (
            <Card className="p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium">Labeling Progress</span>
                <span className="text-sm text-stone-500">
                  {progress.labeled} / {progress.total} labeled ({progress.progress_percent.toFixed(0)}%)
                </span>
              </div>
              <ProgressBar
                total={progress.total}
                segments={[
                  // Each tag with its color
                  ...Object.entries(progress.tag_counts).map(([tagIdStr, count]) => {
                    const tagId = parseInt(tagIdStr);
                    const targetTag = targetTags.find((t) => t.tag_id === tagId);
                    const color = generateTagColor(tagId);
                    const displayName = targetTag
                      ? targetTag.tag.vernacular_name || targetTag.tag.canonical_name || targetTag.tag.value
                      : `Tag ${tagId}`;
                    return { count, color, label: displayName };
                  }),
                  // Negative
                  { count: progress.negative, color: '#ef4444', label: 'Negative' },
                  // Uncertain
                  { count: progress.uncertain, color: '#f59e0b', label: 'Uncertain' },
                  // Unlabeled
                  { count: progress.unlabeled, color: '#3b82f6', label: 'Unlabeled' },
                ]}
                className="mb-2"
              />

              {/* Tag counts display */}
              <div className="flex items-center gap-4 text-xs text-stone-500 flex-wrap">
                {/* Show tag counts if available */}
                {Object.keys(progress.tag_counts).length > 0 ? (
                  <>
                    {Object.entries(progress.tag_counts).map(([tagIdStr, count]) => {
                      const tagId = parseInt(tagIdStr);
                      const targetTag = targetTags.find((t) => t.tag_id === tagId);
                      if (!targetTag) return null;
                      const color = generateTagColor(tagId);
                      const displayName =
                        targetTag.tag.vernacular_name ||
                        targetTag.tag.canonical_name ||
                        targetTag.tag.value;
                      return (
                        <span key={tagId} className="flex items-center gap-1">
                          <span className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
                          {displayName}: {count}
                        </span>
                      );
                    })}
                  </>
                ) : null}
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full bg-red-500" />
                  Negative: {progress.negative}
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full bg-amber-500" />
                  Uncertain: {progress.uncertain}
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full bg-blue-500" />
                  Unlabeled: {progress.unlabeled}
                </span>
              </div>
            </Card>
          )}

          {/* Filter and bulk selection controls */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Filter className="w-4 h-4 text-stone-400" />
                <span className="text-sm text-stone-600 dark:text-stone-400">Filter:</span>
              </div>
              <select
                value={labelFilter}
                onChange={(e) => {
                  setLabelFilter(e.target.value as LabelFilterType);
                  setPage(0);
                  setSelectedIndex(0);
                }}
                className="px-3 py-1.5 text-sm border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
              >
                <option value="all">All labels</option>
                <option value="unlabeled">Unlabeled</option>
                <option value="negative">Negative</option>
                <option value="uncertain">Uncertain</option>
                <option value="skipped">Skipped</option>
                {targetTags.map((targetTag) => {
                  const displayName =
                    targetTag.tag.vernacular_name ||
                    targetTag.tag.canonical_name ||
                    targetTag.tag.value;
                  return (
                    <option key={targetTag.tag_id} value={`tag_${targetTag.tag_id}`}>
                      {displayName}
                    </option>
                  );
                })}
              </select>

              {/* Iteration filter */}
              {session && session.current_iteration > 0 && (
                <select
                  value={iterationFilter ?? "all"}
                  onChange={(e) => {
                    const value = e.target.value;
                    setIterationFilter(value === "all" ? null : parseInt(value));
                    setPage(0);
                    setSelectedIndex(0);
                  }}
                  className="px-3 py-1.5 text-sm border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
                >
                  <option value="all">All iterations</option>
                  {Array.from({ length: session.current_iteration + 1 }, (_, i) => (
                    <option key={i} value={i}>
                      Iteration {i}
                    </option>
                  ))}
                </select>
              )}

              {/* Auto-play toggle */}
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoPlay}
                  onChange={(e) => setAutoPlay(e.target.checked)}
                  className="rounded border-stone-300 text-emerald-600 focus:ring-emerald-500"
                />
                <span className="text-sm text-stone-600 dark:text-stone-400">Auto-play</span>
              </label>

              <span className="text-sm text-stone-500">{totalResults} results</span>
            </div>

            {/* Bulk selection controls */}
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                mode="ghost"
                padding="p-2"
                onClick={() => setShowCheckboxes(!showCheckboxes)}
              >
                {showCheckboxes ? (
                  <MinusSquare className="w-4 h-4" />
                ) : (
                  <Square className="w-4 h-4" />
                )}
                <span className="ml-1 text-sm">Bulk Select</span>
              </Button>
              {showCheckboxes && (
                <>
                  <Button variant="secondary" mode="ghost" padding="p-2" onClick={handleSelectAll}>
                    Select All
                  </Button>
                  <Button
                    variant="secondary"
                    mode="ghost"
                    padding="p-2"
                    onClick={handleDeselectAll}
                  >
                    Deselect All
                  </Button>
                </>
              )}
            </div>
          </div>

          {/* Main content */}
          <div className="grid grid-cols-12 gap-6">
            {/* Results grid */}
            <div className="col-span-8">
              {resultsLoading ? (
                <Loading />
              ) : results.length === 0 ? (
                <Empty>
                  <Music className="w-12 h-12 mb-4 text-stone-400" />
                  <p className="text-lg font-medium">No results found</p>
                  <p className="text-sm text-stone-500 mt-1">
                    {labelFilter !== "all"
                      ? "Try changing the filter to see more results"
                      : "The search did not return any results"}
                  </p>
                </Empty>
              ) : (
                <>
                  <div className="grid grid-cols-4 gap-3">
                    {results.map((result, index) => (
                      <ResultCard
                        key={result.uuid}
                        result={result}
                        isSelected={index === selectedIndex}
                        isChecked={selectedResults.has(result.uuid)}
                        onSelect={() => setSelectedIndex(index)}
                        onCheckToggle={() => handleCheckToggle(result.uuid)}
                        targetTags={targetTags}
                        showCheckbox={showCheckboxes}
                      />
                    ))}
                  </div>

                  {/* Pagination */}
                  {numPages > 1 && (
                    <div className="flex items-center justify-between mt-4">
                      <Button
                        variant="secondary"
                        disabled={page === 0}
                        onClick={() => {
                          setPage(page - 1);
                          setSelectedIndex(0);
                        }}
                      >
                        <ArrowLeft className="w-4 h-4 mr-1" />
                        Previous
                      </Button>
                      <span className="text-sm text-stone-500">
                        Page {page + 1} of {numPages}
                      </span>
                      <Button
                        variant="secondary"
                        disabled={page >= numPages - 1}
                        onClick={() => {
                          setPage(page + 1);
                          setSelectedIndex(0);
                        }}
                      >
                        Next
                        <ArrowRight className="w-4 h-4 ml-1" />
                      </Button>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Labeling panel */}
            <div className="col-span-4 space-y-4">
              {selectedResult && (
                <Card className="p-4">
                  <h4 className="font-medium mb-4">
                    Result #{selectedResult.rank}
                  </h4>
                  {/* Score display with percentile and raw value */}
                  <div className="mb-2 text-sm text-stone-600 dark:text-stone-400">
                    <div className="font-medium">{formatScoreDisplay(selectedResult).percentileText}</div>
                    <div className="text-xs text-stone-500">{formatScoreDisplay(selectedResult).rawValueText}</div>
                  </div>

                  {/* Spectrogram */}
                  <div className="aspect-[2/1] bg-stone-100 dark:bg-stone-800 rounded-lg mb-4 flex items-center justify-center relative overflow-hidden group">
                    <img
                      src={api.spectrograms.getUrl({
                        uuid: selectedResult.clip.recording.uuid,
                        interval: {
                          min: selectedResult.clip.start_time,
                          max: selectedResult.clip.end_time,
                        },
                        ...DEFAULT_SPECTROGRAM_PARAMETERS,
                      })}
                      alt="Spectrogram"
                      className="absolute inset-0 w-full h-full object-cover"
                    />
                    {/* Play button overlay */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        const audio = new Audio(
                          api.audio.getStreamUrl({
                            recording: selectedResult.clip.recording,
                            startTime: selectedResult.clip.start_time,
                            endTime: selectedResult.clip.end_time,
                          })
                        );
                        audio.play();
                      }}
                      className="absolute inset-0 flex items-center justify-center bg-black/0 hover:bg-black/30 transition-colors"
                    >
                      <Play className="w-12 h-12 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                    </button>
                    {/* Sample type and iteration badges */}
                    {selectedResult.sample_type && (
                      <span
                        className={`absolute top-2 left-2 px-2 py-0.5 text-xs rounded-full ${SAMPLE_TYPE_COLORS[selectedResult.sample_type]}`}
                      >
                        {SAMPLE_TYPE_LABELS[selectedResult.sample_type]}
                      </span>
                    )}
                    {selectedResult.iteration_added != null && selectedResult.iteration_added > 0 && (
                      <span className="absolute top-2 right-2 px-2 py-0.5 text-xs bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 rounded-full">
                        Iter {selectedResult.iteration_added}
                      </span>
                    )}
                  </div>

                  {/* Current label */}
                  <div className="mb-4">
                    <span className="text-sm text-stone-500">Current label:</span>
                    {currentLabelStatus?.type === "tagged" ? (
                      <div className="inline-flex items-center gap-1 ml-2 flex-wrap">
                        {/* Multiple tags support */}
                        {currentLabelStatus.tagIds && currentLabelStatus.tagIds.length > 0 ? (
                          currentLabelStatus.tagIds.map((tagId) => {
                            const tag = targetTags.find((t) => t.tag_id === tagId);
                            const color = generateTagColor(tagId);
                            const displayName = tag
                              ? tag.tag.vernacular_name || tag.tag.canonical_name || tag.tag.value
                              : `Tag ${tagId}`;
                            return (
                              <span
                                key={tagId}
                                className="inline-flex items-center gap-1 px-2 py-0.5 text-sm font-medium rounded-full"
                                style={{
                                  backgroundColor: `${color}20`,
                                  color: color,
                                }}
                              >
                                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                                {displayName}
                              </span>
                            );
                          })
                        ) : (
                          /* Single tag fallback */
                          currentAssignedTag && (
                            <span
                              className="inline-flex items-center gap-1 px-2 py-0.5 text-sm font-medium rounded-full"
                              style={{
                                backgroundColor: `${generateTagColor(currentAssignedTag.tag_id)}20`,
                                color: generateTagColor(currentAssignedTag.tag_id),
                              }}
                            >
                              <span
                                className="w-2 h-2 rounded-full"
                                style={{
                                  backgroundColor: generateTagColor(currentAssignedTag.tag_id),
                                }}
                              />
                              {currentAssignedTag.tag.vernacular_name ||
                                currentAssignedTag.tag.canonical_name ||
                                currentAssignedTag.tag.value}
                            </span>
                          )
                        )}
                      </div>
                    ) : (
                      <span
                        className={`ml-2 inline-flex items-center gap-1 px-2 py-0.5 text-sm font-medium rounded-full ${LABEL_STATUS_COLORS[currentLabelStatus?.type || "unlabeled"]}`}
                      >
                        {LABEL_STATUS_ICONS[currentLabelStatus?.type || "unlabeled"]}
                        {currentLabelStatus?.type
                          ? currentLabelStatus.type.charAt(0).toUpperCase() +
                            currentLabelStatus.type.slice(1)
                          : "Unlabeled"}
                      </span>
                    )}
                  </div>

                  {/* Tag label buttons */}
                  {targetTags.length > 0 && (
                    <div className="mb-4">
                      <div className="text-xs text-stone-500 mb-2">Assign to tag (toggle):</div>
                      <div className="flex flex-wrap gap-2">
                        {targetTags
                          .filter((t) => t.shortcut_key <= 9)
                          .map((targetTag) => {
                            // Check if this tag is currently assigned
                            const isActive =
                              (currentLabelStatus?.tagIds &&
                                currentLabelStatus.tagIds.includes(targetTag.tag_id)) ||
                              currentLabelStatus?.tagId === targetTag.tag_id;
                            return (
                              <TagLabelButton
                                key={targetTag.tag_id}
                                targetTag={targetTag}
                                shortcut={String(targetTag.shortcut_key)}
                                onClick={() => handleTagLabel(targetTag.shortcut_key)}
                                active={isActive}
                                disabled={labelMutation.isPending}
                              />
                            );
                          })}
                      </div>
                    </div>
                  )}

                  {/* Special label buttons */}
                  <div className="grid grid-cols-3 gap-2">
                    <SpecialLabelButton
                      label="Negative"
                      shortcut="N"
                      onClick={() => handleLabel({ is_negative: true })}
                      active={currentLabelStatus?.type === "negative"}
                      disabled={labelMutation.isPending}
                      icon={<XCircle className="w-4 h-4" />}
                    />
                    <SpecialLabelButton
                      label="Uncertain"
                      shortcut="U"
                      onClick={() => handleLabel({ is_uncertain: true })}
                      active={currentLabelStatus?.type === "uncertain"}
                      disabled={labelMutation.isPending}
                      icon={<HelpCircle className="w-4 h-4" />}
                    />
                    <SpecialLabelButton
                      label="Skip"
                      shortcut="S"
                      onClick={() => handleLabel({ is_skipped: true })}
                      active={currentLabelStatus?.type === "skipped"}
                      disabled={labelMutation.isPending}
                      icon={<SkipForward className="w-4 h-4" />}
                    />
                  </div>

                  {/* Navigation */}
                  <div className="flex items-center justify-between mt-4 pt-4 border-t border-stone-200 dark:border-stone-700">
                    <Button
                      variant="secondary"
                      mode="text"
                      onClick={handlePrevious}
                      disabled={selectedIndex === 0 && page === 0}
                    >
                      <ArrowLeft className="w-4 h-4 mr-1" />
                      Previous
                    </Button>
                    <Button
                      variant="secondary"
                      mode="text"
                      onClick={handleNext}
                      disabled={selectedIndex >= results.length - 1 && page >= numPages - 1}
                    >
                      Next
                      <ArrowRight className="w-4 h-4 ml-1" />
                    </Button>
                  </div>
                </Card>
              )}

              {/* Keyboard shortcuts help */}
              <KeyboardShortcutsHelp targetTags={targetTags} />
            </div>
          </div>
        </>
      )}

      {/* Bulk action bar */}
      {selectedResults.size > 0 && (
        <BulkActionBar
          selectedCount={selectedResults.size}
          targetTags={targetTags}
          onBulkLabel={(labelData) => bulkLabelMutation.mutate(labelData)}
          onClearSelection={handleDeselectAll}
          isLabeling={bulkLabelMutation.isPending}
        />
      )}

      {/* Export dialog */}
      {showExportDialog && session && progress && (
        <ExportToAnnotationProjectDialog
          isOpen={showExportDialog}
          onClose={() => setShowExportDialog(false)}
          mlProjectUuid={mlProjectUuid}
          searchSession={session}
          progress={progress}
        />
      )}

      {/* Finalize dialog */}
      {showFinalizeDialog && session && progress && (
        <FinalizeSearchSessionDialog
          isOpen={showFinalizeDialog}
          onClose={() => setShowFinalizeDialog(false)}
          mlProjectUuid={mlProjectUuid}
          searchSession={session}
          progress={progress}
        />
      )}

      {/* Iteration parameters dialog */}
      {showIterationDialog && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 overflow-y-auto py-12 px-4">
          <Card className="w-full max-w-2xl p-6">
            <h3 className="text-lg font-semibold mb-4">Run Next Iteration</h3>
            <p className="text-sm text-stone-500 mb-4">
              Configure active learning parameters for the next iteration.
            </p>

            {/* Score distribution histogram */}
            {session && session.current_iteration > 0 && (
              <div className="mb-6 border border-stone-200 dark:border-stone-700 rounded-lg p-4">
                <h4 className="text-sm font-medium mb-3">Score Distribution by Tag and Iteration</h4>
                {scoreLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="w-6 h-6 animate-spin text-stone-400" />
                  </div>
                ) : scoreDistribution?.distributions ? (
                  <ScoreHistogramChart
                    distributions={scoreDistribution.distributions}
                    targetTags={targetTags}
                  />
                ) : (
                  <div className="flex items-center justify-center py-8 text-stone-500">
                    No distribution data available yet
                  </div>
                )}
              </div>
            )}

            {/* Tag selection */}
            <div className="mb-6">
              <label className="block text-sm font-medium mb-3">
                Select Tags for Iteration
              </label>
              <p className="text-xs text-stone-500 mb-3">
                Choose which tags to include in the next iteration. Unchecked tags will be skipped.
              </p>
              <div className="space-y-2 max-h-48 overflow-y-auto border border-stone-200 dark:border-stone-700 rounded-lg p-3">
                {targetTags.map((targetTag) => {
                  const dist = scoreDistribution?.distributions.find(
                    (d) => d.tag_id === targetTag.tag_id && d.iteration === session?.current_iteration
                  );
                  return (
                    <label
                      key={targetTag.tag_id}
                      className="flex items-center gap-3 p-2 rounded-lg hover:bg-stone-50 dark:hover:bg-stone-800 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={selectedTagsForIteration.has(targetTag.tag_id)}
                        onChange={(e) => {
                          setSelectedTagsForIteration((prev) => {
                            const next = new Set(prev);
                            if (e.target.checked) {
                              next.add(targetTag.tag_id);
                            } else {
                              next.delete(targetTag.tag_id);
                            }
                            return next;
                          });
                        }}
                        className="rounded border-stone-300 dark:border-stone-600"
                      />
                      <span
                        className="w-3 h-3 rounded-full flex-shrink-0"
                        style={{ backgroundColor: generateTagColor(targetTag.tag_id) }}
                      />
                      <span className="flex-1 truncate font-medium text-sm">
                        {targetTag.tag.vernacular_name ||
                          targetTag.tag.canonical_name ||
                          targetTag.tag.value}
                      </span>
                      {dist && (
                        <span className="text-xs text-stone-500 flex-shrink-0">
                          +{dist.positive_count} / -{dist.negative_count}
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
            </div>

            <div className="space-y-4 border-t border-stone-200 dark:border-stone-700 pt-4">
              {/* Classifier type selection */}
              <div>
                <label className="block text-sm font-medium mb-2">
                  Classifier Type
                </label>
                <select
                  value={iterationParams.classifier_type}
                  onChange={(e) =>
                    setIterationParams((p) => ({
                      ...p,
                      classifier_type: e.target.value as ClassifierType,
                    }))
                  }
                  className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg text-sm dark:bg-stone-800"
                >
                  <option value="logistic_regression">Logistic Regression (recommended)</option>
                  <option value="svm_linear">Linear SVM</option>
                  <option value="mlp_small">Small Neural Network</option>
                  <option value="mlp_medium">Medium Neural Network</option>
                  <option value="random_forest">Random Forest</option>
                </select>
                <p className="text-xs text-stone-400 mt-1">
                  {iterationParams.classifier_type === "logistic_regression" && "Fast linear classifier (recommended)"}
                  {iterationParams.classifier_type === "svm_linear" && "Linear classifier with margin-based optimization"}
                  {iterationParams.classifier_type === "mlp_small" && "256-unit hidden layer"}
                  {iterationParams.classifier_type === "mlp_medium" && "256+128-unit hidden layers"}
                  {iterationParams.classifier_type === "random_forest" && "Ensemble method, robust to noisy labels"}
                </p>
              </div>

              {/* Uncertainty range */}
              <div>
                <label className="block text-sm font-medium mb-2">
                  Uncertainty Range
                </label>
                <p className="text-xs text-stone-500 mb-2">
                  Samples with model scores in this range will be selected.
                </p>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min="0"
                    max="0.5"
                    step="0.05"
                    value={iterationParams.uncertainty_low}
                    onChange={(e) =>
                      setIterationParams((p) => ({
                        ...p,
                        uncertainty_low: parseFloat(e.target.value) || 0.25,
                      }))
                    }
                    className="w-20 px-2 py-1 border rounded text-sm dark:bg-stone-800 dark:border-stone-600"
                  />
                  <span className="text-stone-500">to</span>
                  <input
                    type="number"
                    min="0.5"
                    max="1"
                    step="0.05"
                    value={iterationParams.uncertainty_high}
                    onChange={(e) =>
                      setIterationParams((p) => ({
                        ...p,
                        uncertainty_high: parseFloat(e.target.value) || 0.75,
                      }))
                    }
                    className="w-20 px-2 py-1 border rounded text-sm dark:bg-stone-800 dark:border-stone-600"
                  />
                </div>
                <p className="text-xs text-stone-400 mt-1">
                  Narrower range = more uncertain samples
                </p>
              </div>

              {/* Samples per iteration */}
              <div>
                <label className="block text-sm font-medium mb-2">
                  Samples to Add
                </label>
                <input
                  type="number"
                  min="5"
                  max="100"
                  value={iterationParams.samples_per_iteration}
                  onChange={(e) =>
                    setIterationParams((p) => ({
                      ...p,
                      samples_per_iteration: parseInt(e.target.value) || 20,
                    }))
                  }
                  className="w-24 px-2 py-1 border rounded text-sm dark:bg-stone-800 dark:border-stone-600"
                />
                <p className="text-xs text-stone-400 mt-1">
                  Number of new samples to add (5-100)
                </p>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-6">
              <Button
                variant="secondary"
                onClick={() => setShowIterationDialog(false)}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() =>
                  runIterationMutation.mutate({
                    ...iterationParams,
                    selected_tag_ids: Array.from(selectedTagsForIteration),
                  })
                }
                disabled={runIterationMutation.isPending || selectedTagsForIteration.size === 0}
              >
                {runIterationMutation.isPending ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <RefreshCw className="w-4 h-4 mr-2" />
                )}
                Run Iteration
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
