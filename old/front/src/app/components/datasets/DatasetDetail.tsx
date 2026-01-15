import DatasetDetailBase from "@/lib/components/datasets/DatasetDetail";

import type { Dataset } from "@/lib/types";

import DatasetActions from "./DatasetActions";
import DatasetAnnotationProjectsSummary from "./DatasetAnnotationProjectsSummary";
import DatasetNotesSummary from "./DatasetNotesSummary";
import DatasetOverview from "./DatasetOverview";
import DatasetUpdate from "./DatasetUpdate";
import DatasetMetadataSummary from "./DatasetMetadataSummary";
import DatasetFoundationModelsSection from "./DatasetFoundationModelsSection";

export default function DatasetDetail({
  dataset,
  onDeleteDataset,
}: {
  dataset: Dataset;
  onDeleteDataset?: () => void;
}) {
  return (
    <DatasetDetailBase
      DatasetActions={
        <DatasetActions dataset={dataset} onDeleteDataset={onDeleteDataset} />
      }
      DatasetNotesSummary={<DatasetNotesSummary dataset={dataset} />}
      DatasetUpdate={<DatasetUpdate dataset={dataset} />}
      DatasetOverview={<DatasetOverview dataset={dataset} />}
      DatasetMetadataSummary={<DatasetMetadataSummary dataset={dataset} />}
      DatasetFoundationModelsSection={
        <DatasetFoundationModelsSection dataset={dataset} />
      }
      DatasetAnnotationProjectsSummary={
        <DatasetAnnotationProjectsSummary dataset={dataset} canCreate={true} />
      }
    />
  );
}
