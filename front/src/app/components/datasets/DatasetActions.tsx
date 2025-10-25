import { useMemo } from "react";
import toast from "react-hot-toast";

import useDataset from "@/app/hooks/api/useDataset";
import useActiveUser from "@/app/hooks/api/useActiveUser";

import DatasetActionsBase from "@/lib/components/datasets/DatasetActions";

import type { Dataset } from "@/lib/types";

export default function DatasetActions({
  dataset,
  onDeleteDataset,
}: {
  dataset: Dataset;
  onDeleteDataset?: () => void;
}) {
  const { data: activeUser } = useActiveUser();
  const { delete: deleteDataset, download } = useDataset({
    uuid: dataset.uuid,
    dataset,
    onDeleteDataset,
  });

  const canDelete = useMemo(() => {
    if (!activeUser) return false;
    return (
      activeUser.is_superuser === true ||
      activeUser.id === dataset.created_by_id
    );
  }, [activeUser, dataset.created_by_id]);

  const handleDelete = canDelete
    ? async () =>
        toast.promise(
          deleteDataset.mutateAsync(dataset),
          {
            loading: "Deleting...",
            success: "Dataset deleted successfuly!",
            error: (err) =>
              `Could not delete dataset.\n\nError: ${err.response.data?.message ?? err.message}`,
          },
          {
            id: "delete-dataset",
            error: {
              duration: 10000,
            },
          },
        )
    : undefined;

  return (
    <DatasetActionsBase
      dataset={dataset}
      canDelete={canDelete}
      onDeleteDataset={handleDelete}
      onDownloadDataset={
        async () =>
          await toast.promise(download("json"), {
            loading: "Downloading...",
            success: "Download complete",
            error: "Failed to download dataset",
          })
      }
    />
  );
}
