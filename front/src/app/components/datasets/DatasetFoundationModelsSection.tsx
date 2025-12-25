"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";

import api from "@/app/api";
import useActiveUser from "@/app/hooks/api/useActiveUser";
import useFoundationModelRunSpecies from "@/app/hooks/api/useFoundationModelRunSpecies";
import useFoundationModelRuns from "@/app/hooks/api/useFoundationModelRuns";
import useFoundationModelSummary from "@/app/hooks/api/useFoundationModelSummary";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import { DialogOverlay } from "@/lib/components/ui/Dialog";
import Loading from "@/lib/components/ui/Loading";

import type {
  Dataset,
  DatasetFoundationModelSummary,
  FoundationModelRun,
  FoundationModelRunCreate,
  Page,
} from "@/lib/types";

function formatRelativeTime(date?: Date | null) {
  if (!date) return "—";
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const STATUS_COLORS: Record<string, string> = {
  queued: "bg-stone-100 text-stone-600",
  running: "bg-blue-100 text-blue-700",
  post_processing: "bg-indigo-100 text-indigo-700",
  completed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  cancelled: "bg-stone-200 text-stone-600",
};

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

function RunFoundationModelDialog({
  isOpen,
  onClose,
  dataset,
  models,
  canRun,
}: {
  isOpen: boolean;
  onClose: () => void;
  dataset: Dataset;
  models: DatasetFoundationModelSummary[];
  canRun: boolean;
}) {
  const queryClient = useQueryClient();
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [threshold, setThreshold] = useState(0.1);

  useEffect(() => {
    if (!selectedSlug && models.length > 0) {
      setSelectedSlug(models[0].foundation_model.slug);
      setThreshold(models[0].foundation_model.default_confidence_threshold);
    }
  }, [models, selectedSlug]);

  const mutation = useMutation({
    mutationFn: async (payload: FoundationModelRunCreate) =>
      await api.foundationModels.createRun(payload),
    onSuccess: () => {
      toast.success("Foundation model run queued");
      void queryClient.invalidateQueries({
        queryKey: ["foundation-models", dataset.uuid, "summary"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["foundation-models", dataset.uuid, "runs"],
      });
      onClose();
    },
    onError: (error: any) => {
      toast.error(
        error?.response?.data?.message ?? "Failed to start foundation model run",
      );
    },
  });

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedSlug) return;
    await mutation.mutateAsync({
      dataset_uuid: dataset.uuid,
      foundation_model_slug: selectedSlug,
      confidence_threshold: threshold,
    });
  };

  if (!isOpen) return null;

  return (
    <DialogOverlay title="Run foundation model" isOpen onClose={onClose}>
      <form onSubmit={handleSubmit} className="w-[420px] space-y-4">
        <div>
          <label className="block text-sm font-semibold text-stone-700 dark:text-stone-200">
            Foundation model
          </label>
          <select
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white p-2 text-sm dark:border-stone-600 dark:bg-stone-800"
            value={selectedSlug ?? ""}
            onChange={(event) => {
              const slug = event.target.value;
              setSelectedSlug(slug);
              const selected = models.find(
                (item) => item.foundation_model.slug === slug,
              );
              if (selected) {
                setThreshold(selected.foundation_model.default_confidence_threshold);
              }
            }}
            disabled={!canRun}
          >
            {models.map((item) => (
              <option key={item.foundation_model.slug} value={item.foundation_model.slug}>
                {item.foundation_model.display_name} (v{item.foundation_model.version})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-semibold text-stone-700 dark:text-stone-200">
            Confidence threshold
          </label>
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={threshold}
            onChange={(event) => setThreshold(Number(event.target.value))}
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white p-2 text-sm dark:border-stone-600 dark:bg-stone-800"
            disabled={!canRun}
          />
          <p className="mt-1 text-xs text-stone-500">
            Use a single threshold for detections and embeddings (default 0.10).
          </p>
        </div>

        {!canRun ? (
          <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-700 dark:bg-amber-900/30 dark:text-amber-200">
            You need manager access to this dataset to run foundation models.
          </p>
        ) : null}

        <div className="flex justify-end gap-2">
          <Button mode="ghost" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={!canRun || mutation.isPending || !selectedSlug}
            variant="primary"
            mode="filled"
          >
            {mutation.isPending ? "Queuing..." : "Run"}
          </Button>
        </div>
      </form>
    </DialogOverlay>
  );
}

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
  const [filterSlug, setFilterSlug] = useState<string | undefined>(undefined);
  const [offset, setOffset] = useState(0);
  const limit = 10;
  const runsQuery = useFoundationModelRuns({
    datasetUuid,
    foundationModelSlug: filterSlug,
    limit,
    offset,
  });

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
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-200 dark:divide-stone-700">
                  {page.items.map((run) => (
                    <tr key={run.uuid}>
                      <td className="px-3 py-2">
                        {run.foundation_model?.display_name ?? run.foundation_model_id}
                      </td>
                      <td className="px-3 py-2">
                        <StatusBadge run={run} />
                      </td>
                      <td className="px-3 py-2">
                        {run.requested_by?.email ?? "—"}
                      </td>
                      <td className="px-3 py-2">
                        {run.started_on ? formatRelativeTime(run.started_on) : "—"}
                      </td>
                      <td className="px-3 py-2">
                        {run.completed_on ? formatRelativeTime(run.completed_on) : "—"}
                      </td>
                    </tr>
                  ))}
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

export default function DatasetFoundationModelsSection({
  dataset,
}: {
  dataset: Dataset;
}) {
  const { data: activeUser } = useActiveUser();
  const summaryQuery = useFoundationModelSummary(dataset.uuid);
  const models = summaryQuery.data ?? [];

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
    () =>
      models.find(
        (item) => item.foundation_model.slug === selectedSlug,
      ),
    [models, selectedSlug],
  );
  const latestRun =
    selectedSummary?.last_completed_run ?? selectedSummary?.latest_run;
  const speciesQuery = useFoundationModelRunSpecies(latestRun?.uuid);
  const speciesRows = speciesQuery.data?.species ?? [];

  const [isDialogOpen, setDialogOpen] = useState(false);
  const [isHistoryOpen, setHistoryOpen] = useState(false);

  const canRun =
    activeUser != null &&
    (activeUser.is_superuser || activeUser.id === dataset.created_by_id);

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-stone-900 dark:text-stone-50">
            Run foundation models
          </h3>
          <p className="mt-1 text-sm text-stone-500 dark:text-stone-300">
            Execute BirdNET or Perch on this dataset to generate species classifications and embeddings.
          </p>
        </div>
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
            onClick={() => setDialogOpen(true)}
            disabled={!canRun || models.length === 0}
          >
            Run foundation models
          </Button>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
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

        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold uppercase tracking-wide text-stone-500">
              Species summary
            </h4>
            {latestRun ? (
              <span className="text-xs text-stone-500">
                Last run:{" "}
                {formatRelativeTime(
                  latestRun.completed_on ??
                    latestRun.started_on ??
                    latestRun.created_on,
                )}
              </span>
            ) : null}
          </div>
          {speciesQuery.isLoading ? (
            <Loading />
          ) : speciesRows.length === 0 ? (
            <p className="text-sm text-stone-500">
              {latestRun
                ? "No detections above the current threshold."
                : "Select a model to see results."}
            </p>
          ) : (
            <div className="max-h-[320px] overflow-y-auto rounded-lg border border-stone-200 text-sm dark:border-stone-700">
              <table className="min-w-full divide-y divide-stone-200 dark:divide-stone-700">
                <thead className="bg-stone-50 text-xs uppercase tracking-wide text-stone-500 dark:bg-stone-800">
                  <tr>
                    <th className="px-3 py-2 text-left">Scientific name</th>
                    <th className="px-3 py-2 text-left">Common name (JA)</th>
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
                        {row.common_name_ja ?? "—"}
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
          {latestRun ? (
            <Button
              mode="ghost"
              onClick={() =>
                window.open(
                  `/annotation-projects/new?dataset=${dataset.uuid}&foundation_run=${latestRun.uuid}`,
                  "_blank",
                )
              }
            >
              Create annotation project from this result
            </Button>
          ) : null}
        </div>
      </div>

      <RunFoundationModelDialog
        isOpen={isDialogOpen}
        onClose={() => setDialogOpen(false)}
        dataset={dataset}
        models={models}
        canRun={canRun}
      />
      <RunHistoryDrawer
        isOpen={isHistoryOpen}
        onClose={() => setHistoryOpen(false)}
        datasetUuid={dataset.uuid}
        models={models}
      />
    </Card>
  );
}
