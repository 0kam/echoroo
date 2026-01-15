"use client";

/**
 * Custom Model detail page.
 *
 * Displays model information, score histogram, and provides
 * links to source search session, annotation project, and inference.
 */
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import {
  ArrowLeft,
  Cpu,
  Target,
  Layers,
  Clock,
  CheckCircle,
  XCircle,
  Loader2,
  Archive,
  Rocket,
  ExternalLink,
  Play,
} from "lucide-react";

// Dynamically import Plotly to avoid SSR issues
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

import api from "@/app/api";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Loading from "@/lib/components/ui/Loading";
import Link from "@/lib/components/ui/Link";

import type {
  CustomModel,
  CustomModelStatus,
  CustomModelType,
  TagScoreDistribution,
  SearchSessionTargetTag,
} from "@/lib/types";

// Status badge colors
const STATUS_COLORS: Record<CustomModelStatus, string> = {
  draft: "bg-stone-200 text-stone-700 dark:bg-stone-700 dark:text-stone-300",
  training: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  trained: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  failed: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  deployed: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
  archived: "bg-stone-300 text-stone-600 dark:bg-stone-600 dark:text-stone-400",
};

const STATUS_ICONS: Record<CustomModelStatus, React.ReactNode> = {
  draft: <Clock className="w-4 h-4" />,
  training: <Loader2 className="w-4 h-4 animate-spin" />,
  trained: <CheckCircle className="w-4 h-4" />,
  failed: <XCircle className="w-4 h-4" />,
  deployed: <Rocket className="w-4 h-4" />,
  archived: <Archive className="w-4 h-4" />,
};

const MODEL_TYPE_LABELS: Record<CustomModelType, string> = {
  svm: "Self-Training SVM",
};

function StatusBadge({ status }: { status: CustomModelStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-3 py-1.5 text-sm font-medium rounded-full ${STATUS_COLORS[status]}`}
    >
      {STATUS_ICONS[status]}
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

// Score histogram chart component
function ScoreHistogramChart({
  distributions,
  selectedIteration,
}: {
  distributions: TagScoreDistribution[];
  selectedIteration?: number | null;
}) {
  if (!distributions || distributions.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-stone-500">
        No distribution data available
      </div>
    );
  }

  // Filter by selected iteration if specified
  const filteredDistributions = selectedIteration != null
    ? distributions.filter((d) => d.iteration === selectedIteration)
    : distributions;

  // Group distributions by tag_id
  const distributionsByTag = filteredDistributions.reduce((acc, dist) => {
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
    const tagName = tagDists[0]?.tag_name || `Tag ${tagId}`;

    // Sort by iteration
    tagDists.sort((a, b) => a.iteration - b.iteration);

    tagDists.forEach((dist, iterIdx) => {
      const color = iterationColors[dist.iteration % iterationColors.length];

      // Create bin centers from bin_edges for x-axis
      const binCenters = dist.bin_edges.slice(0, -1).map((edge, i) => {
        return (edge + dist.bin_edges[i + 1]) / 2;
      });

      // Add histogram bars for unlabeled data
      traces.push({
        x: binCenters,
        y: dist.bin_counts,
        type: "bar",
        name: `Iter ${dist.iteration}`,
        marker: { color: color, opacity: 0.7 },
        xaxis: `x${tagIndex + 1}`,
        yaxis: `y${tagIndex + 1}`,
        legendgroup: `iter${dist.iteration}`,
        showlegend: tagIndex === 0,
      });

      // Add scatter trace for training positive scores
      if (dist.training_positive_scores && dist.training_positive_scores.length > 0) {
        traces.push({
          x: dist.training_positive_scores,
          y: dist.training_positive_scores.map(() => 1),
          type: "scatter",
          mode: "markers",
          name: "Training Positive",
          marker: {
            color: "#10b981",
            size: 8,
            symbol: "circle",
            line: { color: "white", width: 1 },
          },
          xaxis: `x${tagIndex + 1}`,
          yaxis: `y${tagIndex + 1}`,
          legendgroup: "training_positive",
          showlegend: tagIndex === 0 && iterIdx === 0,
        });
      }

      // Add scatter trace for training negative scores
      if (dist.training_negative_scores && dist.training_negative_scores.length > 0) {
        traces.push({
          x: dist.training_negative_scores,
          y: dist.training_negative_scores.map(() => 1),
          type: "scatter",
          mode: "markers",
          name: "Training Negative",
          marker: {
            color: "#ef4444",
            size: 8,
            symbol: "circle",
            line: { color: "white", width: 1 },
          },
          xaxis: `x${tagIndex + 1}`,
          yaxis: `y${tagIndex + 1}`,
          legendgroup: "training_negative",
          showlegend: tagIndex === 0 && iterIdx === 0,
        });
      }
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
  const gapBetweenSubplots = 0.15;
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

export default function ModelDetailPage() {
  const params = useParams();
  const router = useRouter();
  const mlProjectUuid = params.ml_project_uuid as string;
  const modelUuid = params.model_uuid as string;

  // Fetch model details
  const { data: model, isLoading: modelLoading } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "custom_model", modelUuid],
    queryFn: () => api.customModels.get(mlProjectUuid, modelUuid),
    enabled: !!mlProjectUuid && !!modelUuid,
  });

  // Fetch score distribution if model has source search session
  const { data: scoreDistribution, isLoading: scoreLoading } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_session", model?.source_search_session_uuid, "score_distribution"],
    queryFn: () => api.searchSessions.getScoreDistribution(mlProjectUuid, model!.source_search_session_uuid!),
    enabled: !!mlProjectUuid && !!model?.source_search_session_uuid,
  });

  if (modelLoading) {
    return <Loading />;
  }

  if (!model) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <p className="text-stone-500">Model not found</p>
        <Button
          variant="secondary"
          className="mt-4"
          onClick={() => router.push(`/ml-projects/${mlProjectUuid}/training`)}
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back to Models
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button
          variant="secondary"
          mode="text"
          onClick={() => router.push(`/ml-projects/${mlProjectUuid}/training`)}
        >
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold text-stone-900 dark:text-stone-100">
              {model.name}
            </h1>
            <StatusBadge status={model.status} />
          </div>
          {model.description && (
            <p className="text-stone-500 dark:text-stone-400 mt-1">
              {model.description}
            </p>
          )}
        </div>
      </div>

      {/* Model Info and Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Model Info */}
        <Card className="lg:col-span-2">
          <h2 className="text-lg font-medium mb-4">Model Information</h2>
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-3">
              <Cpu className="w-5 h-5 text-stone-400" />
              <span className="text-stone-600 dark:text-stone-400 w-32">Model Type:</span>
              <span className="font-medium">{MODEL_TYPE_LABELS[model.model_type]}</span>
            </div>
            <div className="flex items-center gap-3">
              <Target className="w-5 h-5 text-stone-400" />
              <span className="text-stone-600 dark:text-stone-400 w-32">Target Tag:</span>
              <span className="font-medium">{model.tag.key}: {model.tag.value}</span>
            </div>
            <div className="flex items-center gap-3">
              <Layers className="w-5 h-5 text-stone-400" />
              <span className="text-stone-600 dark:text-stone-400 w-32">Training Data:</span>
              <span className="font-medium">
                {model.metrics?.training_samples ?? 0} samples
              </span>
            </div>
          </div>

          {/* Links */}
          <div className="mt-6 pt-4 border-t border-stone-200 dark:border-stone-700 space-y-3">
            {model.source_search_session_uuid && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-stone-500">Source Search Session:</span>
                <Link
                  href={`/ml-projects/${mlProjectUuid}/search/${model.source_search_session_uuid}`}
                  className="text-sm text-emerald-600 dark:text-emerald-400 hover:underline flex items-center gap-1"
                >
                  {model.source_search_session_name || "View Session"}
                  <ExternalLink className="w-3 h-3" />
                </Link>
              </div>
            )}
            {model.annotation_project_uuid && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-stone-500">Annotation Project:</span>
                <Link
                  href={`/ml-projects/${mlProjectUuid}/annotation-projects/${model.annotation_project_uuid}`}
                  className="text-sm text-emerald-600 dark:text-emerald-400 hover:underline flex items-center gap-1"
                >
                  {model.annotation_project_name || "View Project"}
                  <ExternalLink className="w-3 h-3" />
                </Link>
              </div>
            )}
          </div>
        </Card>

        {/* Actions */}
        <Card>
          <h2 className="text-lg font-medium mb-4">Actions</h2>
          <div className="space-y-3">
            {(model.status === "trained" || model.status === "deployed") && (
              <Button
                variant="primary"
                className="w-full"
                onClick={() => router.push(`/ml-projects/${mlProjectUuid}/inference?model=${model.uuid}`)}
              >
                <Play className="w-4 h-4 mr-2" />
                Use in Inference
              </Button>
            )}
            <Button
              variant="secondary"
              className="w-full"
              onClick={() => router.push(`/ml-projects/${mlProjectUuid}/training`)}
            >
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Models
            </Button>
          </div>
        </Card>
      </div>

      {/* Score Distribution Histogram */}
      {model.source_search_session_uuid && (
        <Card>
          <h2 className="text-lg font-medium mb-4">Score Distribution</h2>
          {scoreLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-8 h-8 animate-spin text-stone-400" />
            </div>
          ) : scoreDistribution && scoreDistribution.distributions.length > 0 ? (
            <ScoreHistogramChart distributions={scoreDistribution.distributions} />
          ) : (
            <div className="flex items-center justify-center py-8 text-stone-500">
              No score distribution data available
            </div>
          )}
        </Card>
      )}

      {/* Error message (if failed) */}
      {model.status === "failed" && model.error_message && (
        <Card>
          <h2 className="text-lg font-medium mb-4 text-red-600">Error</h2>
          <p className="text-sm text-red-600 dark:text-red-400">{model.error_message}</p>
        </Card>
      )}
    </div>
  );
}
