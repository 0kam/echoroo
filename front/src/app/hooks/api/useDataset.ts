import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import api from "@/app/api";

import useObject from "@/lib/hooks/utils/useObject";

import type { Dataset, DatasetUpdate } from "@/lib/types";

/**
 * Custom hook for managing dataset-related state, fetching, and mutations.
 *
 * This hook encapsulates the logic for querying, updating, and deleting
 * dataset information using React Query. It can also fetch and provide
 * additional dataset state if enabled.
 */
export default function useDataset({
  uuid,
  dataset,
  enabled = true,
  withState = false,
  onUpdateDataset,
  onDeleteDataset,
  onError,
}: {
  uuid: string;
  dataset?: Dataset;
  enabled?: boolean;
  withState?: boolean;
  onUpdateDataset?: (updated: Dataset) => void;
  onDeleteDataset?: (deleted: Dataset) => void;
  onError?: (error: AxiosError) => void;
}) {
  const queryClient = useQueryClient();

  if (dataset !== undefined && dataset.uuid !== uuid) {
    throw new Error("Dataset uuid does not match");
  }

  const { query, useMutation } = useObject<Dataset>({
    id: uuid,
    initialData: dataset,
    name: "dataset",
    enabled,
    queryFn: api.datasets.get,
    onError,
  });

  const update = useMutation<DatasetUpdate>({
    mutationFn: api.datasets.update,
    onSuccess: (data) => {
      // Invalidate related queries to ensure UI consistency
      queryClient.invalidateQueries({ queryKey: ["dataset", uuid, "stats"] });
      queryClient.invalidateQueries({ queryKey: ["dataset_recordings"] });
      onUpdateDataset?.(data);
    },
  });

  const delete_ = useMutation({
    mutationFn: api.datasets.delete,
    onSuccess: (data) => {
      onDeleteDataset?.(data);
    },
  });

  const state = useQuery({
    queryKey: ["dataset", uuid, "state"],
    queryFn: async () => await api.datasets.getState(uuid),
    enabled: withState,
  });

  return {
    ...query,
    update,
    delete: delete_,
    state,
  };
}
