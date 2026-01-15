"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { Loader2, ChevronDown, ChevronUp, Cpu, Play, Save } from "lucide-react";

import { DialogOverlay } from "@/lib/components/ui/Dialog";
import Button from "@/lib/components/ui/Button";

import api from "@/app/api";

import type {
  SearchSession,
  SearchSessionTargetTag,
  TrainModelRequest,
  AddSamplesRequest,
  FinalizeRequest,
  TagScoreDistribution,
} from "@/lib/schemas/search_sessions";

// Import ScoreHistogramChart component from search session page
// We'll extract it or duplicate it here for now
import dynamic from "next/dynamic";
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

interface TrainModelDialogProps {
  isOpen: boolean;
  onClose: () => void;
  mlProjectUuid: string;
  searchSession: SearchSession;
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

// Deploy form component
interface DeployFormProps {
  modelName: string;
  setModelName: (value: string) => void;
  description: string;
  setDescription: (value: string) => void;
  createAnnotationProject: boolean;
  setCreateAnnotationProject: (value: boolean) => void;
  annotationProjectName: string;
  setAnnotationProjectName: (value: string) => void;
  onDeploy: () => void;
  isDeploying: boolean;
  title?: string;
}

function DeployForm({
  modelName,
  setModelName,
  description,
  setDescription,
  createAnnotationProject,
  setCreateAnnotationProject,
  annotationProjectName,
  setAnnotationProjectName,
  onDeploy,
  isDeploying,
  title = "Deploy Model",
}: DeployFormProps) {
  return (
    <div className="border border-stone-200 dark:border-stone-700 rounded-lg p-4 bg-stone-50 dark:bg-stone-900">
      <h4 className="text-sm font-medium mb-4">{title}</h4>
      <div className="space-y-4">
        {/* Model Name */}
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Model Name *
          </label>
          <input
            type="text"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg text-sm bg-white dark:bg-stone-800"
            placeholder="Enter model name"
            required
          />
        </div>

        {/* Description */}
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Description
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg text-sm bg-white dark:bg-stone-800"
            placeholder="Enter model description (optional)"
            rows={3}
          />
        </div>

        {/* Create Annotation Project */}
        <div>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={createAnnotationProject}
              onChange={(e) => setCreateAnnotationProject(e.target.checked)}
              className="rounded border-stone-300 dark:border-stone-600"
            />
            <span className="text-sm text-stone-700 dark:text-stone-300">
              Create Annotation Project
            </span>
          </label>
        </div>

        {/* Annotation Project Name (conditional) */}
        {createAnnotationProject && (
          <div>
            <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
              Annotation Project Name
            </label>
            <input
              type="text"
              value={annotationProjectName}
              onChange={(e) => setAnnotationProjectName(e.target.value)}
              className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg text-sm bg-white dark:bg-stone-800"
              placeholder={modelName || "Enter annotation project name"}
            />
            <p className="text-xs text-stone-400 mt-1">
              Defaults to model name if not specified
            </p>
          </div>
        )}

        <Button
          variant="primary"
          onClick={onDeploy}
          disabled={isDeploying || !modelName.trim()}
        >
          {isDeploying ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Deploying...
            </>
          ) : (
            <>
              <Save className="w-4 h-4 mr-2" />
              Deploy Model
            </>
          )}
        </Button>
      </div>
    </div>
  );
}

// ScoreHistogramChart component (duplicated from search session page)
function ScoreHistogramChart({
  distributions,
  targetTags,
  selectedIteration,
}: {
  distributions: TagScoreDistribution[];
  targetTags: SearchSessionTargetTag[];
  selectedIteration?: number | null; // null or undefined = show all
}) {
  if (!distributions || distributions.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-stone-500">
        No distribution data available yet
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
        showlegend: tagIndex === 0, // Only show legend for first tag
      });

      // Add scatter trace for training positive scores
      if (dist.training_positive_scores && dist.training_positive_scores.length > 0) {
        traces.push({
          x: dist.training_positive_scores,
          y: dist.training_positive_scores.map(() => 1), // Position at y=1 for visibility
          type: "scatter",
          mode: "markers",
          name: "Training Positive",
          marker: {
            color: "#10b981", // green
            size: 8,
            symbol: "circle",
            line: { color: "white", width: 1 },
          },
          xaxis: `x${tagIndex + 1}`,
          yaxis: `y${tagIndex + 1}`,
          legendgroup: "training_positive",
          showlegend: tagIndex === 0 && iterIdx === 0, // Only show once in legend
        });
      }

      // Add scatter trace for training negative scores
      if (dist.training_negative_scores && dist.training_negative_scores.length > 0) {
        traces.push({
          x: dist.training_negative_scores,
          y: dist.training_negative_scores.map(() => 1), // Position at y=1 for visibility
          type: "scatter",
          mode: "markers",
          name: "Training Negative",
          marker: {
            color: "#ef4444", // red
            size: 8,
            symbol: "circle",
            line: { color: "white", width: 1 },
          },
          xaxis: `x${tagIndex + 1}`,
          yaxis: `y${tagIndex + 1}`,
          legendgroup: "training_negative",
          showlegend: tagIndex === 0 && iterIdx === 0, // Only show once in legend
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

export default function TrainModelDialog({
  isOpen,
  onClose,
  mlProjectUuid,
  searchSession,
}: TrainModelDialogProps) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const targetTags = searchSession.target_tags || [];

  const [showNextIterationForm, setShowNextIterationForm] = useState(false);
  const [showDeployForm, setShowDeployForm] = useState(false);
  const [trainingStep, setTrainingStep] = useState<string>("");

  // Next Iteration form state
  const [uncertaintyLow, setUncertaintyLow] = useState(0.25);
  const [uncertaintyHigh, setUncertaintyHigh] = useState(0.75);
  const [sampleCount, setSampleCount] = useState(20);

  // Deploy form state
  const [modelName, setModelName] = useState(`Model from ${searchSession.name}`);
  const [description, setDescription] = useState("");
  const [createAnnotationProject, setCreateAnnotationProject] = useState(true);
  const [annotationProjectName, setAnnotationProjectName] = useState("");

  // Iteration filter for histogram
  const [selectedHistogramIteration, setSelectedHistogramIteration] = useState<number | null>(null);

  // Fetch previous score distribution when dialog opens
  const { data: previousScoreDistribution, isLoading: isLoadingPrevious } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_session", searchSession.uuid, "score_distribution"],
    queryFn: () => api.searchSessions.getScoreDistribution(mlProjectUuid, searchSession.uuid),
    enabled: isOpen && searchSession.current_iteration > 0,
  });

  // Helper function to extract error message from API errors
  const getErrorMessage = (error: unknown): string => {
    if (error && typeof error === "object" && "response" in error) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      if (axiosError.response?.data?.detail) {
        return axiosError.response.data.detail;
      }
    }
    if (error instanceof Error) {
      return error.message;
    }
    return "Unknown error";
  };

  // Train model mutation
  const trainMutation = useMutation({
    mutationFn: async (data?: TrainModelRequest) => {
      setTrainingStep("Fetching labeled data...");
      await new Promise((resolve) => setTimeout(resolve, 300));

      setTrainingStep("Training classifiers...");
      const result = await api.searchSessions.trainModel(mlProjectUuid, searchSession.uuid, data);

      setTrainingStep("Computing score distributions...");
      await new Promise((resolve) => setTimeout(resolve, 300));

      setTrainingStep("");
      return result;
    },
    onError: (error) => {
      setTrainingStep("");
      toast.error(`Failed to train model: ${getErrorMessage(error)}`);
    },
  });

  // Add samples mutation
  const addSamplesMutation = useMutation({
    mutationFn: (data: AddSamplesRequest) =>
      api.searchSessions.addSamples(mlProjectUuid, searchSession.uuid, data),
    onSuccess: (data) => {
      toast.success(`Added ${data.added_count} new samples`);
      // Invalidate relevant queries
      queryClient.invalidateQueries({
        queryKey: ["ml_project", mlProjectUuid, "search_session", searchSession.uuid],
      });
      queryClient.invalidateQueries({
        queryKey: ["ml_project", mlProjectUuid, "search_session", searchSession.uuid, "results"],
      });
      queryClient.invalidateQueries({
        queryKey: ["ml_project", mlProjectUuid, "search_session", searchSession.uuid, "progress"],
      });
      onClose(); // Close dialog and return to labeling
    },
    onError: (error) => {
      toast.error(`Failed to add samples: ${getErrorMessage(error)}`);
    },
  });

  // Deploy mutation
  const deployMutation = useMutation({
    mutationFn: (data: FinalizeRequest) =>
      api.searchSessions.finalize(mlProjectUuid, searchSession.uuid, data),
    onSuccess: (result) => {
      const message = createAnnotationProject && result.annotation_project_uuid
        ? `Model "${result.custom_model_name}" and Annotation Project "${result.annotation_project_name}" created successfully!`
        : `Model "${result.custom_model_name}" created successfully!`;

      toast.success(message);

      // Invalidate relevant queries
      queryClient.invalidateQueries({ queryKey: ["ml_project_custom_models", mlProjectUuid] });
      if (createAnnotationProject) {
        queryClient.invalidateQueries({ queryKey: ["ml_project_annotation_projects", mlProjectUuid] });
      }

      onClose();

      // Navigate to Models tab
      router.push(`/ml-projects/${mlProjectUuid}/models`);
    },
    onError: (error) => {
      toast.error(`Failed to deploy: ${getErrorMessage(error)}`);
    },
  });

  // Reset state when dialog closes
  useEffect(() => {
    if (!isOpen) {
      setShowNextIterationForm(false);
      setShowDeployForm(false);
      setTrainingStep("");
      trainMutation.reset();
    }
  }, [isOpen]);

  // Handle Next Iteration
  const handleAddSamples = useCallback(() => {
    addSamplesMutation.mutate({
      uncertainty_low: uncertaintyLow,
      uncertainty_high: uncertaintyHigh,
      samples_per_iteration: sampleCount,
    });
  }, [uncertaintyLow, uncertaintyHigh, sampleCount, addSamplesMutation]);

  // Handle Deploy
  const handleDeploy = useCallback(() => {
    if (!modelName.trim()) {
      toast.error("Please enter a model name");
      return;
    }

    const deployData: FinalizeRequest = {
      model_name: modelName.trim(),
      create_annotation_project: createAnnotationProject,
      annotation_project_name: createAnnotationProject
        ? (annotationProjectName.trim() || modelName.trim())
        : undefined,
      description: description.trim() || undefined,
    };

    deployMutation.mutate(deployData);
  }, [modelName, createAnnotationProject, annotationProjectName, description, deployMutation]);

  return (
    <DialogOverlay
      title="Train Model"
      isOpen={isOpen}
      onClose={onClose}
    >
      <div className="w-[800px] max-h-[90vh] overflow-y-auto flex flex-col gap-6">
        {/* Initial state: Show previous results and Train button */}
        {!trainMutation.isPending && !trainMutation.data && !trainMutation.isError && (
          <>
            {/* Previous score distribution */}
            {previousScoreDistribution && previousScoreDistribution.distributions.length > 0 && (
              <div className="border border-stone-200 dark:border-stone-700 rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <h4 className="text-sm font-medium">
                    Previous Training Results
                  </h4>
                  <select
                    value={selectedHistogramIteration ?? "all"}
                    onChange={(e) => setSelectedHistogramIteration(
                      e.target.value === "all" ? null : parseInt(e.target.value)
                    )}
                    className="text-sm border border-stone-300 dark:border-stone-600 rounded px-2 py-1 bg-white dark:bg-stone-800"
                  >
                    <option value="all">All Iterations</option>
                    {Array.from(new Set(previousScoreDistribution.distributions.map((d) => d.iteration)))
                      .sort((a, b) => a - b)
                      .map((iter) => (
                        <option key={iter} value={iter}>
                          Iteration {iter}
                        </option>
                      ))}
                  </select>
                </div>
                <ScoreHistogramChart
                  distributions={previousScoreDistribution.distributions}
                  targetTags={targetTags}
                  selectedIteration={selectedHistogramIteration}
                />
              </div>
            )}

            {isLoadingPrevious && (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-8 h-8 animate-spin text-stone-400" />
              </div>
            )}

            {/* Action buttons */}
            <div className="flex flex-col items-center gap-4 py-8">
              <p className="text-sm text-stone-600 dark:text-stone-400">
                Train a new model or deploy the current one
              </p>
              <div className="flex gap-3">
                <Button
                  variant="primary"
                  onClick={() => trainMutation.mutate(undefined)}
                  className="px-8"
                >
                  <Cpu className="w-4 h-4 mr-2" />
                  Train Model
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setShowDeployForm(!showDeployForm)}
                  disabled={searchSession.current_iteration === 0 || isLoadingPrevious}
                  className="px-8"
                >
                  <Save className="w-4 h-4 mr-2" />
                  Deploy
                </Button>
              </div>
              {searchSession.current_iteration === 0 && (
                <p className="text-xs text-stone-400">
                  Train a model first before deploying
                </p>
              )}
            </div>

            {/* Deploy form (collapsible) - shown in initial state */}
            {showDeployForm && (
              <DeployForm
                modelName={modelName}
                setModelName={setModelName}
                description={description}
                setDescription={setDescription}
                createAnnotationProject={createAnnotationProject}
                setCreateAnnotationProject={setCreateAnnotationProject}
                annotationProjectName={annotationProjectName}
                setAnnotationProjectName={setAnnotationProjectName}
                onDeploy={handleDeploy}
                isDeploying={deployMutation.isPending}
                title="Deploy Current Model"
              />
            )}
          </>
        )}

        {/* Training in progress */}
        {trainMutation.isPending && (
          <div className="flex flex-col items-center justify-center py-12">
            <Loader2 className="w-12 h-12 animate-spin text-emerald-500 mb-4" />
            <p className="text-lg font-medium">Training model...</p>
            {trainingStep && (
              <p className="text-sm text-emerald-600 dark:text-emerald-400 mt-2 animate-pulse">
                {trainingStep}
              </p>
            )}
            <p className="text-sm text-stone-500 mt-1">This may take a few moments</p>
          </div>
        )}

        {/* Training error */}
        {trainMutation.isError && (
          <div className="flex flex-col items-center justify-center py-12">
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-6 max-w-md">
              <h4 className="text-lg font-semibold text-red-900 dark:text-red-100 mb-2">
                Training Failed
              </h4>
              <p className="text-sm text-red-700 dark:text-red-300 mb-4">
                {getErrorMessage(trainMutation.error)}
              </p>
              <div className="flex gap-3">
                <Button
                  variant="primary"
                  onClick={() => trainMutation.mutate(undefined)}
                >
                  Try Again
                </Button>
                <Button
                  variant="secondary"
                  onClick={onClose}
                >
                  Close
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Training results */}
        {trainMutation.data && (
          <>
            {/* Histogram display */}
            <div className="border border-stone-200 dark:border-stone-700 rounded-lg p-4">
              <h4 className="text-sm font-medium mb-3">Score Distribution</h4>
              <ScoreHistogramChart
                distributions={trainMutation.data.score_distributions}
                targetTags={targetTags}
              />
            </div>

            {/* Training metrics */}
            <div className="bg-stone-100 dark:bg-stone-800 rounded-lg p-4">
              <h4 className="text-sm font-medium mb-3">Training Metrics</h4>
              <div className="grid grid-cols-2 gap-3">
                {Object.entries(trainMutation.data.training_metrics).map(([tagIdStr, metrics]: [string, { positive_count: number; negative_count: number }]) => {
                  const tagId = parseInt(tagIdStr);
                  const targetTag = targetTags.find((t) => t.tag_id === tagId);
                  const tagName = targetTag
                    ? targetTag.tag.vernacular_name || targetTag.tag.canonical_name || targetTag.tag.value
                    : `Tag ${tagId}`;
                  const color = generateTagColor(tagId);

                  return (
                    <div
                      key={tagId}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white dark:bg-stone-900 border border-stone-200 dark:border-stone-700"
                    >
                      <span
                        className="w-3 h-3 rounded-full flex-shrink-0"
                        style={{ backgroundColor: color }}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium truncate">{tagName}</div>
                        <div className="text-xs text-stone-500">
                          +{metrics.positive_count} / -{metrics.negative_count}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-2 border-t border-stone-200 dark:border-stone-700 pt-4">
              <Button
                variant="secondary"
                onClick={() => setShowNextIterationForm(!showNextIterationForm)}
                disabled={addSamplesMutation.isPending || deployMutation.isPending}
              >
                {showNextIterationForm ? (
                  <ChevronUp className="w-4 h-4 mr-2" />
                ) : (
                  <ChevronDown className="w-4 h-4 mr-2" />
                )}
                Next Iteration
              </Button>

              <Button
                variant="secondary"
                onClick={() => setShowDeployForm(!showDeployForm)}
                disabled={addSamplesMutation.isPending || deployMutation.isPending}
              >
                {showDeployForm ? (
                  <ChevronUp className="w-4 h-4 mr-2" />
                ) : (
                  <ChevronDown className="w-4 h-4 mr-2" />
                )}
                Deploy
              </Button>

              <div className="flex-1" />

              <Button
                variant="secondary"
                onClick={onClose}
                disabled={addSamplesMutation.isPending || deployMutation.isPending}
              >
                Close
              </Button>
            </div>

            {/* Next Iteration form (collapsible) */}
            {showNextIterationForm && (
              <div className="border border-stone-200 dark:border-stone-700 rounded-lg p-4 bg-stone-50 dark:bg-stone-900">
                <h4 className="text-sm font-medium mb-4">Add Samples for Next Iteration</h4>
                <div className="space-y-4">
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
                        value={uncertaintyLow}
                        onChange={(e) => setUncertaintyLow(parseFloat(e.target.value) || 0.25)}
                        className="w-24 px-3 py-2 border rounded-lg text-sm dark:bg-stone-800 dark:border-stone-600"
                      />
                      <span className="text-stone-500">to</span>
                      <input
                        type="number"
                        min="0.5"
                        max="1"
                        step="0.05"
                        value={uncertaintyHigh}
                        onChange={(e) => setUncertaintyHigh(parseFloat(e.target.value) || 0.75)}
                        className="w-24 px-3 py-2 border rounded-lg text-sm dark:bg-stone-800 dark:border-stone-600"
                      />
                    </div>
                  </div>

                  {/* Samples to add */}
                  <div>
                    <label className="block text-sm font-medium mb-2">
                      Samples to Add
                    </label>
                    <input
                      type="number"
                      min="5"
                      max="100"
                      value={sampleCount}
                      onChange={(e) => setSampleCount(parseInt(e.target.value) || 20)}
                      className="w-32 px-3 py-2 border rounded-lg text-sm dark:bg-stone-800 dark:border-stone-600"
                    />
                    <p className="text-xs text-stone-400 mt-1">
                      Number of new samples to add (5-100)
                    </p>
                  </div>

                  <Button
                    variant="primary"
                    onClick={handleAddSamples}
                    disabled={addSamplesMutation.isPending}
                  >
                    {addSamplesMutation.isPending ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Adding...
                      </>
                    ) : (
                      <>
                        <Play className="w-4 h-4 mr-2" />
                        Add Samples
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}

            {/* Deploy form (collapsible) */}
            {showDeployForm && (
              <DeployForm
                modelName={modelName}
                setModelName={setModelName}
                description={description}
                setDescription={setDescription}
                createAnnotationProject={createAnnotationProject}
                setCreateAnnotationProject={setCreateAnnotationProject}
                annotationProjectName={annotationProjectName}
                setAnnotationProjectName={setAnnotationProjectName}
                onDeploy={handleDeploy}
                isDeploying={deployMutation.isPending}
              />
            )}
          </>
        )}
      </div>
    </DialogOverlay>
  );
}
