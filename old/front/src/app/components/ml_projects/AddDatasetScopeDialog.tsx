"use client";

/**
 * Dialog for adding a dataset scope to an ML project.
 *
 * Allows selecting a dataset and its corresponding foundation model run
 * to add as a scope for similarity search.
 */
import { useState, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Database, Cpu } from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import { DialogOverlay } from "@/lib/components/ui/Dialog";

import type { MLProjectDatasetScopeCreate } from "@/lib/types";

interface AddDatasetScopeDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: MLProjectDatasetScopeCreate) => void;
  isSubmitting: boolean;
}

export default function AddDatasetScopeDialog({
  isOpen,
  onClose,
  onSubmit,
  isSubmitting,
}: AddDatasetScopeDialogProps) {
  const [selectedDatasetUuid, setSelectedDatasetUuid] = useState<string>("");
  const [selectedRunUuid, setSelectedRunUuid] = useState<string>("");

  // Fetch available datasets
  const { data: datasetsData, isLoading: isLoadingDatasets } = useQuery({
    queryKey: ["datasets", "list"],
    queryFn: () => api.datasets.getMany({ limit: 100 }),
    enabled: isOpen,
  });

  const datasets = useMemo(
    () => datasetsData?.items ?? [],
    [datasetsData],
  );

  // Fetch foundation model runs for the selected dataset
  const { data: runsData, isLoading: isLoadingRuns } = useQuery({
    queryKey: ["foundation_model_runs", "dataset", selectedDatasetUuid],
    queryFn: () =>
      api.foundationModels.listRuns({
        dataset_uuid: selectedDatasetUuid,
        status: "completed",
        limit: 100,
      }),
    enabled: !!selectedDatasetUuid,
  });

  const runs = useMemo(
    () => runsData?.items ?? [],
    [runsData],
  );

  // Reset run selection when dataset changes
  const handleDatasetChange = useCallback((uuid: string) => {
    setSelectedDatasetUuid(uuid);
    setSelectedRunUuid("");
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedDatasetUuid || !selectedRunUuid) return;

    onSubmit({
      dataset_uuid: selectedDatasetUuid,
      foundation_model_run_uuid: selectedRunUuid,
    });
  };

  const handleClose = () => {
    setSelectedDatasetUuid("");
    setSelectedRunUuid("");
    onClose();
  };

  const canSubmit = selectedDatasetUuid && selectedRunUuid && !isSubmitting;

  return (
    <DialogOverlay
      title="Add Dataset Scope"
      isOpen={isOpen}
      onClose={handleClose}
    >
      <form onSubmit={handleSubmit} className="w-[450px] space-y-5">
        <p className="text-sm text-stone-500 dark:text-stone-400">
          Select a dataset and foundation model run to use as a scope for
          similarity search.
        </p>

        {/* Dataset Selection */}
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1.5">
            <Database className="w-4 h-4 inline-block mr-1.5" />
            Dataset
          </label>
          {isLoadingDatasets ? (
            <div className="flex items-center gap-2 text-sm text-stone-500">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading datasets...
            </div>
          ) : datasets.length === 0 ? (
            <p className="text-sm text-stone-500">No datasets available</p>
          ) : (
            <select
              value={selectedDatasetUuid}
              onChange={(e) => handleDatasetChange(e.target.value)}
              className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100 focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500"
              required
            >
              <option value="">Select a dataset</option>
              {datasets.map((dataset) => (
                <option key={dataset.uuid} value={dataset.uuid}>
                  {dataset.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Foundation Model Run Selection */}
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1.5">
            <Cpu className="w-4 h-4 inline-block mr-1.5" />
            Foundation Model Run
          </label>
          {!selectedDatasetUuid ? (
            <p className="text-sm text-stone-500 italic">
              Select a dataset first
            </p>
          ) : isLoadingRuns ? (
            <div className="flex items-center gap-2 text-sm text-stone-500">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading runs...
            </div>
          ) : runs.length === 0 ? (
            <p className="text-sm text-stone-500">
              No completed runs found for this dataset
            </p>
          ) : (
            <select
              value={selectedRunUuid}
              onChange={(e) => setSelectedRunUuid(e.target.value)}
              className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100 focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500"
              required
            >
              <option value="">Select a run</option>
              {runs.map((run) => (
                <option key={run.uuid} value={run.uuid}>
                  {run.foundation_model?.display_name ?? "Unknown Model"} -{" "}
                  {new Date(run.created_on).toLocaleDateString()} (
                  {run.total_clips ?? 0} clips)
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-4 border-t border-stone-200 dark:border-stone-600">
          <Button type="button" variant="secondary" onClick={handleClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={!canSubmit}>
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Adding...
              </>
            ) : (
              "Add Dataset"
            )}
          </Button>
        </div>
      </form>
    </DialogOverlay>
  );
}
