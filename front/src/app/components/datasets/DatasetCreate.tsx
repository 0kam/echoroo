import { useMutation, useQuery } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";

import api from "@/app/api";

import DatasetCreateBase from "@/lib/components/datasets/DatasetCreate";

import type { Dataset, DatasetCreate } from "@/lib/types";

export default function DatasetCreate({
  onCreateDataset,
  onError,
  defaultProjectId,
}: {
  onCreateDataset?: (project: Dataset) => void;
  onError?: (error: AxiosError) => void;
  defaultProjectId?: string;
}) {
  const [pollingDatasetId, setPollingDatasetId] = useState<string | null>(
    null,
  );

  const { mutateAsync } = useMutation({
    mutationFn: api.datasets.create,
    onError: onError,
  });

  // Polling: check status every 2 seconds
  const { data: pollingDataset } = useQuery({
    queryKey: ["dataset", pollingDatasetId],
    queryFn: () => api.datasets.get(pollingDatasetId!),
    enabled: !!pollingDatasetId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 2000;
      // Poll every 2 seconds if processing, stop if completed/failed
      const processingStatuses = ["pending", "scanning", "processing"];
      return processingStatuses.includes(data.status || "pending")
        ? 2000
        : false;
    },
  });

  // Handle polling results
  useEffect(() => {
    if (!pollingDataset) return;

    if (pollingDataset.status === "completed") {
      toast.success("Dataset created successfully");
      toast.dismiss("dataset-processing");
      setPollingDatasetId(null);
      onCreateDataset?.(pollingDataset);
    } else if (pollingDataset.status === "failed") {
      toast.error(
        `Failed: ${pollingDataset.processing_error || "Unknown error"}`,
      );
      toast.dismiss("dataset-processing");
      setPollingDatasetId(null);
    } else if (pollingDataset.status === "processing") {
      const progress = pollingDataset.processing_progress || 0;
      const processed = pollingDataset.processed_files || 0;
      const total = pollingDataset.total_files || 0;
      toast.loading(
        `Processing... ${progress}% (${processed}/${total} files)`,
        { id: "dataset-processing" },
      );
    } else if (pollingDataset.status === "scanning") {
      toast.loading("Scanning files...", { id: "dataset-processing" });
    }
  }, [pollingDataset, onCreateDataset]);

  const handleCreateProject = useCallback(
    async (data: DatasetCreate) => {
      try {
        const dataset = await mutateAsync(data);
        toast.success("Dataset creation started");
        setPollingDatasetId(dataset.uuid); // Start polling
      } catch (error) {
        toast.error("Failed to create dataset");
      }
    },
    [mutateAsync],
  );

  return (
    <DatasetCreateBase
      onCreateDataset={handleCreateProject}
      defaultProjectId={defaultProjectId}
    />
  );
}
