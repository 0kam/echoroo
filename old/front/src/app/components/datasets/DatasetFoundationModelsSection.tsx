"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { FilterIcon, Trash2 } from "lucide-react";
import toast from "react-hot-toast";

import api from "@/app/api";
import useActiveUser from "@/app/hooks/api/useActiveUser";
import useFoundationModelRunSpecies from "@/app/hooks/api/useFoundationModelRunSpecies";
import useFoundationModelRuns from "@/app/hooks/api/useFoundationModelRuns";
import useFoundationModelSummary from "@/app/hooks/api/useFoundationModelSummary";

import {
  RunFoundationModelDialog,
  FoundationModelProgressCard,
  ConvertToAnnotationDialog,
} from "@/app/components/foundation_models";
import {
  ApplySpeciesFilterDialog,
  FilterProgressCard,
  FilterSummaryPanel,
  SpeciesFilterResultsPanel,
} from "@/app/components/species_filters";
import { DetectionVisualizationPanel } from "@/app/components/detection_visualization";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import { DialogOverlay } from "@/lib/components/ui/Dialog";
import Loading from "@/lib/components/ui/Loading";

import type {
  Dataset,
  DatasetFoundationModelSummary,
  FoundationModelRun,
  FoundationModelRunStatus,
  Page,
  SpeciesFilterApplication,
} from "@/lib/types";
import { canEditDataset } from "@/lib/utils/permissions";

// ============================================================================
// Utility: Format relative time
// ============================================================================

function formatRelativeTime(date?: Date | null) {
  if (!date) return "---";
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// ============================================================================
// Status Colors
// ============================================================================

const STATUS_COLORS: Record<string, string> = {
  queued: "bg-stone-100 text-stone-600",
  running: "bg-blue-100 text-blue-700",
  post_processing: "bg-indigo-100 text-indigo-700",
  completed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-stone-200 text-stone-600",
};

// ============================================================================
// Type Guards
// ============================================================================

function isActiveRunStatus(status: FoundationModelRunStatus): boolean {
  return status === "queued" || status === "running" || status === "post_processing";
}

function isCompletedRunStatus(status: FoundationModelRunStatus): boolean {
  return status === "completed";
}

// ============================================================================
// Status Badge Component
// ============================================================================

function StatusBadge({ run }: { run?: FoundationModelRun | null }) {
  if (!run) return <span className="text-sm text-stone-500">Not run</span>;
  const className =
    STATUS_COLORS[run.status] ??
    "bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-300";
  const timestamp = run.completed_on ?? run.started_on ?? run.created_on;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium ${className}`}
    >
      {run.status.replace("_", " ")}
      {timestamp ? (
        <span className="text-[10px] text-stone-600 dark:text-stone-300">
          {formatRelativeTime(timestamp)}
        </span>
      ) : null}
    </span>
  );
}

// ============================================================================
// Run History Drawer
// ============================================================================

function RunHistoryDrawer({
  isOpen,
  onClose,
  datasetUuid,
  models,
}: {
  isOpen: boolean;
  onClose: () => void;
  datasetUuid: string;
  models: DatasetFoundationModelSummary[];
}) {
  const queryClient = useQueryClient();
  const [filterSlug, setFilterSlug] = useState<string | undefined>(undefined);
  const [offset, setOffset] = useState(0);
  const [deletingRunUuid, setDeletingRunUuid] = useState<string | null>(null);
  const limit = 10;
  const runsQuery = useFoundationModelRuns({
    datasetUuid,
    foundationModelSlug: filterSlug,
    limit,
    offset,
  });

  const deleteMutation = useMutation({
    mutationFn: ({ runUuid }: { runUuid: string }) => {
      setDeletingRunUuid(runUuid);
      return api.foundationModels.deleteRun(runUuid);
    },
    onSuccess: () => {
      setDeletingRunUuid(null);
      toast.success("Foundation model run deleted successfully");
      void runsQuery.refetch();
      void queryClient.invalidateQueries({
        queryKey: ["foundation-models", datasetUuid],
      });
    },
    onError: (error) => {
      setDeletingRunUuid(null);
      console.error("Failed to delete run:", error);
      toast.error("Failed to delete foundation model run");
    },
  });

  const handleDelete = useCallback((run: FoundationModelRun) => {
    if (run.status === "running" || run.status === "queued" || run.status === "post_processing") {
      toast.error("Cannot delete a run that is currently in progress");
      return;
    }

    const confirmMessage =
      "Are you sure you want to delete this foundation model run?\n\n" +
      "This will permanently delete:\n" +
      "- All species predictions\n" +
      "- All detection results\n" +
      "- All associated embeddings\n\n" +
      "This action cannot be undone.";

    if (window.confirm(confirmMessage)) {
      deleteMutation.mutate({ runUuid: run.uuid });
    }
  }, [deleteMutation]);

  useEffect(() => {
    setOffset(0);
  }, [filterSlug]);

  if (!isOpen) return null;

  const page = runsQuery.data as Page<FoundationModelRun> | undefined;
  const hasNext = page ? page.offset + page.limit < page.total : false;
  const hasPrev = page ? page.offset > 0 : false;

  return (
    <DialogOverlay
      title="Foundation model run history"
      isOpen
      onClose={onClose}
    >
      <div className="w-[720px] space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <select
            className="rounded-md border border-stone-300 bg-white p-2 text-sm dark:border-stone-600 dark:bg-stone-800"
            value={filterSlug ?? ""}
            onChange={(event) =>
              setFilterSlug(event.target.value || undefined)
            }
          >
            <option value="">All foundation models</option>
            {models.map((item) => (
              <option
                key={item.foundation_model.slug}
                value={item.foundation_model.slug}
              >
                {item.foundation_model.display_name}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            <Button
              mode="ghost"
              disabled={!hasPrev}
              onClick={() => setOffset(Math.max(0, offset - limit))}
            >
              Previous
            </Button>
            <Button
              mode="ghost"
              disabled={!hasNext}
              onClick={() => setOffset(offset + limit)}
            >
              Next
            </Button>
          </div>
        </div>
        <div className="max-h-[420px] overflow-y-auto rounded-xl border border-stone-200 dark:border-stone-700">
          {runsQuery.isLoading ? (
            <div className="p-6">
              <Loading />
            </div>
          ) : page && page.items.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-stone-200 text-sm dark:divide-stone-700">
                <thead className="bg-stone-50 text-xs uppercase tracking-wide text-stone-500 dark:bg-stone-800">
                  <tr>
                    <th className="px-3 py-2 text-left">Model</th>
                    <th className="px-3 py-2 text-left">Status</th>
                    <th className="px-3 py-2 text-left">Requested by</th>
                    <th className="px-3 py-2 text-left">Started</th>
                    <th className="px-3 py-2 text-left">Completed</th>
                    <th className="px-3 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-200 dark:divide-stone-700">
                  {page.items.map((run) => {
                    const isRunning = run.status === "running" || run.status === "queued" || run.status === "post_processing";
                    return (
                      <tr key={run.uuid}>
                        <td className="px-3 py-2">
                          {run.foundation_model?.display_name ?? run.foundation_model_id}
                        </td>
                        <td className="px-3 py-2">
                          <StatusBadge run={run} />
                        </td>
                        <td className="px-3 py-2">
                          {run.requested_by?.email ?? "---"}
                        </td>
                        <td className="px-3 py-2">
                          {run.started_on ? formatRelativeTime(run.started_on) : "---"}
                        </td>
                        <td className="px-3 py-2">
                          {run.completed_on ? formatRelativeTime(run.completed_on) : "---"}
                        </td>
                        <td className="px-3 py-2 text-right">
                          <button
                            onClick={() => handleDelete(run)}
                            disabled={isRunning || deletingRunUuid === run.uuid}
                            title={isRunning ? "Cannot delete a run in progress" : deletingRunUuid === run.uuid ? "Deleting..." : "Delete this run and all associated predictions"}
                            className={`inline-flex items-center justify-center rounded-lg p-1.5 transition-colors ${
                              isRunning || deletingRunUuid === run.uuid
                                ? "cursor-not-allowed text-stone-300 dark:text-stone-600"
                                : "text-stone-400 hover:bg-red-50 hover:text-red-600 dark:text-stone-400 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                            }`}
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-6 text-sm text-stone-500">No runs yet.</div>
          )}
        </div>
      </div>
    </DialogOverlay>
  );
}

// ============================================================================
// Main Component
// ============================================================================

export default function DatasetFoundationModelsSection({
  dataset,
}: {
  dataset: Dataset;
}) {
  const queryClient = useQueryClient();
  const { data: activeUser } = useActiveUser();
  const summaryQuery = useFoundationModelSummary(dataset.uuid);
  const models = useMemo(() => summaryQuery.data ?? [], [summaryQuery.data]);

  // Job queue status query
  const queueStatusQuery = useQuery({
    queryKey: ["foundation-models", "queue-status"],
    queryFn: () => api.foundationModels.getQueueStatus(),
    refetchInterval: 10_000, // Refresh every 10 seconds
    staleTime: 5_000,
  });
  const queueStatus = queueStatusQuery.data;

  // Selected model slug for the model list
  const [selectedSlug, setSelectedSlug] = useState<string | undefined>(undefined);
  useEffect(() => {
    if (models.length === 0) {
      setSelectedSlug(undefined);
      return;
    }
    if (!selectedSlug || !models.find((item) => item.foundation_model.slug === selectedSlug)) {
      setSelectedSlug(models[0].foundation_model.slug);
    }
  }, [models, selectedSlug]);

  const selectedSummary = useMemo(
    () => models.find((item) => item.foundation_model.slug === selectedSlug),
    [models, selectedSlug],
  );

  // Determine the run to display (latest or in-progress)
  const latestRun = selectedSummary?.latest_run;
  const lastCompletedRun = selectedSummary?.last_completed_run;

  // Determine the current run state
  // Prefer pending run (just created) over summary data for immediate feedback
  const activeRunFromSummary = latestRun && isActiveRunStatus(latestRun.status) ? latestRun : null;
  const completedRun = lastCompletedRun ?? (latestRun && isCompletedRunStatus(latestRun.status) ? latestRun : null);

  // Dialog state
  const [isRunDialogOpen, setRunDialogOpen] = useState(false);
  const [isHistoryOpen, setHistoryOpen] = useState(false);
  const [isApplyFilterDialogOpen, setApplyFilterDialogOpen] = useState(false);
  const [isSpeciesResultsOpen, setSpeciesResultsOpen] = useState(false);

  // Track newly created run for immediate progress display
  const [pendingRunUuid, setPendingRunUuid] = useState<string | null>(null);
  const pendingRunQuery = useQuery({
    queryKey: ["foundation-models", "runs", pendingRunUuid],
    enabled: Boolean(pendingRunUuid),
    queryFn: async () => {
      if (!pendingRunUuid) throw new Error("runUuid is required");
      return await api.foundationModels.getRun(pendingRunUuid);
    },
    // Poll every 2 seconds while the run is active
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && isActiveRunStatus(data.status)) {
        return 2000;
      }
      return false;
    },
  });
  const pendingRun = pendingRunQuery.data;

  // Effective active run: prefer pendingRun for immediate UI feedback
  const activeRun = useMemo(() => {
    // If we have a pending run that's still active, use it
    if (pendingRun && isActiveRunStatus(pendingRun.status)) {
      return pendingRun;
    }
    // Otherwise fall back to summary data
    return activeRunFromSummary;
  }, [pendingRun, activeRunFromSummary]);

  // Clear pending run when it appears in the summary or when it completes/fails
  useEffect(() => {
    if (!pendingRunUuid) return;
    // If the latest run from summary matches, clear the pending run
    if (latestRun?.uuid === pendingRunUuid) {
      setPendingRunUuid(null);
    }
    // If the pending run has completed or failed, clear it
    if (pendingRun && !isActiveRunStatus(pendingRun.status)) {
      setPendingRunUuid(null);
    }
  }, [pendingRunUuid, latestRun?.uuid, pendingRun]);

  // Species summary query (for legacy species table)
  const speciesQuery = useFoundationModelRunSpecies(completedRun?.uuid);
  const speciesRows = speciesQuery.data?.species ?? [];

  // Convert to annotation dialog state
  const [isConvertDialogOpen, setConvertDialogOpen] = useState(false);

  // Species filter application state
  const [activeFilterApplication, setActiveFilterApplication] = useState<SpeciesFilterApplication | null>(null);
  const [showFilterProgress, setShowFilterProgress] = useState(false);

  // Fetch species filter applications for the completed run
  const filterApplicationsQuery = useQuery({
    queryKey: ["foundation_model_run", completedRun?.uuid, "filter_applications"],
    queryFn: () => api.speciesFilters.listApplications(completedRun!.uuid),
    enabled: !!completedRun?.uuid,
    staleTime: 30_000,
  });

  // Determine the latest filter application
  const filterApplications = useMemo(
    () => filterApplicationsQuery.data ?? [],
    [filterApplicationsQuery.data],
  );

  const latestFilterApplication = useMemo(() => {
    if (filterApplications.length === 0) return null;
    // Find the most recent completed or running application
    const sorted = [...filterApplications].sort((a, b) => {
      const aTime = a.completed_on ? new Date(a.completed_on).getTime() : 0;
      const bTime = b.completed_on ? new Date(b.completed_on).getTime() : 0;
      return bTime - aTime;
    });
    return sorted[0] ?? null;
  }, [filterApplications]);

  // Determine if there is a filter in progress
  const filterInProgress = useMemo(() => {
    return filterApplications.find(
      (app) => app.status === "pending" || app.status === "running"
    ) ?? null;
  }, [filterApplications]);

  // Permission check
  const canRun = canEditDataset(activeUser, dataset, dataset.project ?? undefined);

  // Common invalidation function
  const invalidateFoundationModelQueries = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: ["foundation-models", dataset.uuid],
    });
  }, [queryClient, dataset.uuid]);

  // Callback handlers
  const handleRunCreated = useCallback((runUuid: string) => {
    // Immediately set pending run to show progress card
    setPendingRunUuid(runUuid);
    invalidateFoundationModelQueries();
  }, [invalidateFoundationModelQueries]);

  const handleRunCompleted = useCallback(() => {
    invalidateFoundationModelQueries();
  }, [invalidateFoundationModelQueries]);

  const handleRunCancelled = useCallback(() => {
    invalidateFoundationModelQueries();
  }, [invalidateFoundationModelQueries]);

  const handleFilterApplied = useCallback((application: SpeciesFilterApplication) => {
    setActiveFilterApplication(application);
    setShowFilterProgress(true);
    void queryClient.invalidateQueries({
      queryKey: ["foundation_model_run", completedRun?.uuid, "filter_applications"],
    });
  }, [queryClient, completedRun?.uuid]);

  const handleFilterComplete = useCallback(() => {
    setShowFilterProgress(false);
    void queryClient.invalidateQueries({
      queryKey: ["foundation_model_run", completedRun?.uuid, "filter_applications"],
    });
  }, [queryClient, completedRun?.uuid]);

  const handleFilterCancelled = useCallback(() => {
    setShowFilterProgress(false);
    setActiveFilterApplication(null);
    void queryClient.invalidateQueries({
      queryKey: ["foundation_model_run", completedRun?.uuid, "filter_applications"],
    });
  }, [queryClient, completedRun?.uuid]);

  const handleReapplyFilter = useCallback((_threshold: number) => {
    setApplyFilterDialogOpen(true);
  }, []);

  const handleViewExcluded = useCallback(() => {
    setSpeciesResultsOpen(true);
  }, []);

  return (
    <Card>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-stone-900 dark:text-stone-50">
            Run foundation models
          </h3>
          <p className="mt-1 text-sm text-stone-500 dark:text-stone-300">
            Execute BirdNET or Perch on this dataset to generate species classifications and embeddings.
          </p>
        </div>
        <div className="flex items-center gap-4">
          {/* Queue Status */}
          {queueStatus && (queueStatus.pending > 0 || queueStatus.running > 0) && (
            <div className="flex items-center gap-2 rounded-lg bg-stone-100 px-3 py-1.5 text-sm dark:bg-stone-800">
              {queueStatus.running > 0 && (
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-blue-500" />
                  <span className="text-stone-600 dark:text-stone-300">
                    {queueStatus.running} running
                  </span>
                </span>
              )}
              {queueStatus.pending > 0 && (
                <span className="text-stone-500 dark:text-stone-400">
                  {queueStatus.pending} queued
                </span>
              )}
            </div>
          )}
          <div className="flex gap-2">
            <Button
              mode="ghost"
              onClick={() => setHistoryOpen(true)}
              disabled={summaryQuery.isLoading || models.length === 0}
            >
              View run history
            </Button>
            <Button
              mode="filled"
              variant="primary"
              onClick={() => setRunDialogOpen(true)}
              disabled={!canRun}
            >
              Run foundation models
            </Button>
          </div>
        </div>
      </div>

      {/* Content Grid */}
      <div className="mt-6 grid gap-6 lg:grid-cols-[280px_1fr]">
        {/* Left Column: Model List */}
        <div className="space-y-4">
          <h4 className="text-sm font-semibold uppercase tracking-wide text-stone-500">
            Executed models
          </h4>
          {summaryQuery.isLoading ? (
            <Loading />
          ) : models.length === 0 ? (
            <p className="text-sm text-stone-500">No foundation models registered.</p>
          ) : (
            <div className="space-y-3">
              {models.map((item) => (
                <button
                  key={item.foundation_model.slug}
                  type="button"
                  className={`w-full rounded-xl border p-3 text-left transition hover:border-emerald-400 ${
                    item.foundation_model.slug === selectedSlug
                      ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20"
                      : "border-stone-200 dark:border-stone-700"
                  }`}
                  onClick={() => setSelectedSlug(item.foundation_model.slug)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <div className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                        {item.foundation_model.display_name}{" "}
                        <span className="text-xs text-stone-500">
                          v{item.foundation_model.version}
                        </span>
                      </div>
                      <div className="text-xs text-stone-500">
                        Default threshold:{" "}
                        {item.foundation_model.default_confidence_threshold.toFixed(2)}
                      </div>
                    </div>
                    <StatusBadge run={item.latest_run} />
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Right Column: Results or Progress */}
        <div className="space-y-4">
          {/* Show progress card when a run is in progress */}
          {activeRun && (
            <FoundationModelProgressCard
              run={activeRun}
              onCancelled={handleRunCancelled}
              onComplete={handleRunCompleted}
            />
          )}

          {/* Show species summary when a run is completed and no active run */}
          {!activeRun && completedRun && (
            <>
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-semibold uppercase tracking-wide text-stone-500">
                  Species summary
                </h4>
                <span className="text-xs text-stone-500">
                  Last run:{" "}
                  {formatRelativeTime(
                    completedRun.completed_on ??
                      completedRun.started_on ??
                      completedRun.created_on,
                  )}
                </span>
              </div>

              {speciesQuery.isLoading ? (
                <Loading />
              ) : speciesRows.length === 0 ? (
                <p className="text-sm text-stone-500">
                  No detections above the current threshold.
                </p>
              ) : (
                <div className="max-h-[320px] overflow-y-auto rounded-lg border border-stone-200 text-sm dark:border-stone-700">
                  <table className="min-w-full divide-y divide-stone-200 dark:divide-stone-700">
                    <thead className="bg-stone-50 text-xs uppercase tracking-wide text-stone-500 dark:bg-stone-800">
                      <tr>
                        <th className="px-3 py-2 text-left">Scientific name</th>
                        <th className="px-3 py-2 text-left">Common name</th>
                        <th className="px-3 py-2 text-right">Detections</th>
                        <th className="px-3 py-2 text-right">Avg confidence</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-stone-200 dark:divide-stone-700">
                      {speciesRows.map((row) => (
                        <tr key={`${row.scientific_name}-${row.gbif_taxon_id ?? ""}`}>
                          <td className="px-3 py-2 font-medium text-stone-900 dark:text-stone-100">
                            {row.scientific_name}
                          </td>
                          <td className="px-3 py-2 text-stone-500">
                            {row.vernacular_name ?? "---"}
                          </td>
                          <td className="px-3 py-2 text-right">
                            {row.detection_count}
                          </td>
                          <td className="px-3 py-2 text-right">
                            {(row.avg_confidence * 100).toFixed(1)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex flex-wrap gap-2">
                <Button
                  mode="filled"
                  variant="primary"
                  onClick={() => setConvertDialogOpen(true)}
                  disabled={!canRun}
                >
                  Convert to Annotation Project
                </Button>
                <Button
                  mode="outline"
                  variant="secondary"
                  onClick={() => setApplyFilterDialogOpen(true)}
                  disabled={!canRun}
                >
                  <FilterIcon className="mr-1.5 h-4 w-4" />
                  Apply species filter
                </Button>
              </div>
            </>
          )}

          {/* Show empty state when no run exists */}
          {!activeRun && !completedRun && !summaryQuery.isLoading && (
            <div className="rounded-lg border border-dashed border-stone-300 p-6 text-center dark:border-stone-600">
              <p className="text-sm text-stone-500">
                Select a model and run it to see results.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Species Filter Section */}
      {completedRun && (filterInProgress || latestFilterApplication) && (
        <div className="mt-6 border-t border-stone-200 pt-6 dark:border-stone-700">
          <h4 className="mb-4 text-sm font-semibold uppercase tracking-wide text-stone-500">
            Species Filter
          </h4>

          {/* Show progress card when filter is being applied */}
          {(filterInProgress || (showFilterProgress && activeFilterApplication)) && (
            <FilterProgressCard
              runUuid={completedRun.uuid}
              applicationUuid={(filterInProgress ?? activeFilterApplication)!.uuid}
              initialData={filterInProgress ?? activeFilterApplication ?? undefined}
              onComplete={handleFilterComplete}
              onCancel={handleFilterCancelled}
            />
          )}

          {/* Show summary panel when filter is completed */}
          {!filterInProgress && !showFilterProgress && latestFilterApplication && latestFilterApplication.status === "completed" && (
            <FilterSummaryPanel
              application={latestFilterApplication}
              onReapply={handleReapplyFilter}
              onViewExcluded={handleViewExcluded}
            />
          )}
        </div>
      )}

      {/* Detection Visualization Section */}
      {completedRun && (
        <div className="mt-6 border-t border-stone-200 pt-6 dark:border-stone-700">
          <h4 className="mb-4 text-sm font-semibold uppercase tracking-wide text-stone-500">
            Detection Patterns
          </h4>
          <DetectionVisualizationPanel
            runUuid={completedRun.uuid}
            filterApplicationUuid={
              latestFilterApplication?.status === "completed"
                ? latestFilterApplication.uuid
                : undefined
            }
          />
        </div>
      )}

      {/* Run Foundation Model Dialog */}
      <RunFoundationModelDialog
        isOpen={isRunDialogOpen}
        onClose={() => setRunDialogOpen(false)}
        datasetUuid={dataset.uuid}
        recordingCount={dataset.recording_count}
        canRun={canRun}
        onRunCreated={handleRunCreated}
      />

      {/* Run History Drawer */}
      <RunHistoryDrawer
        isOpen={isHistoryOpen}
        onClose={() => setHistoryOpen(false)}
        datasetUuid={dataset.uuid}
        models={models}
      />

      {/* Apply Species Filter Dialog */}
      {completedRun && (
        <ApplySpeciesFilterDialog
          runUuid={completedRun.uuid}
          open={isApplyFilterDialogOpen}
          onOpenChange={setApplyFilterDialogOpen}
          onFilterApplied={handleFilterApplied}
          recordingsWithoutLocation={0}
          totalRecordings={dataset.recording_count}
        />
      )}

      {/* Species Filter Results Dialog */}
      {completedRun && latestFilterApplication && (
        <DialogOverlay
          title="Species Filter Results"
          isOpen={isSpeciesResultsOpen}
          onClose={() => setSpeciesResultsOpen(false)}
        >
          <div className="w-[600px] max-w-full">
            <SpeciesFilterResultsPanel
              runUuid={completedRun.uuid}
              applicationUuid={latestFilterApplication.uuid}
              onConvertToAnnotation={() => {
                setSpeciesResultsOpen(false);
                setConvertDialogOpen(true);
              }}
            />
          </div>
        </DialogOverlay>
      )}

      {/* Convert to Annotation Project Dialog */}
      {completedRun && (
        <ConvertToAnnotationDialog
          runUuid={completedRun.uuid}
          hasFilterApplied={
            !!latestFilterApplication &&
            latestFilterApplication.status === "completed"
          }
          filterApplicationUuid={latestFilterApplication?.uuid}
          modelName={completedRun.foundation_model?.display_name}
          open={isConvertDialogOpen}
          onOpenChange={setConvertDialogOpen}
          onSuccess={(annotationProjectUuid) => {
            // Navigate to the new annotation project
            window.location.href = `/annotation_projects/${annotationProjectUuid}`;
          }}
          onApplyFilter={() => setApplyFilterDialogOpen(true)}
        />
      )}
    </Card>
  );
}
