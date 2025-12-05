import Pagination from "@/app/components/Pagination";
import DatasetCreate from "@/app/components/datasets/DatasetCreate";
import DatasetImport from "@/app/components/datasets/DatasetImport";
import VisibilityFilterChips, {
  type VisibilityFilterValue,
} from "@/app/components/datasets/VisibilityFilterChips";

import { useMemo } from "react";
import { useSearchParams } from "next/navigation";

import useDatasets from "@/app/hooks/api/useDatasets";
import useDatasetFilterOptions from "@/app/hooks/ui/useDatasetFilterOptions";

import DatasetListBase from "@/lib/components/datasets/DatasetList";
import { AnnotationProjectIcon } from "@/lib/components/icons";
import Search from "@/lib/components/inputs/Search";
import { Select } from "@/lib/components/inputs";
import Button from "@/lib/components/ui/Button";

import type { Dataset } from "@/lib/types";

/**
 * Component to display a list of datasets along with search functionality,
 * create and import links.
 */
export default function DatasetList({
  onCreateDataset,
  onClickDataset,
}: {
  onCreateDataset?: (dataset: Dataset) => void;
  onClickDataset?: (dataset: Dataset) => void;
}) {
  const searchParams = useSearchParams();
  const initialProjectId =
    searchParams.get("project_id") ?? searchParams.get("project_id__eq") ?? "";

  const initialFilter = useMemo(
    () =>
      initialProjectId
        ? ({
            project_id__eq: initialProjectId,
          } as const)
        : undefined,
    [initialProjectId],
  );

  const { items, pagination, isLoading, filter } = useDatasets({
    filter: initialFilter,
    onCreateDataset,
  });
  const searchValue = (filter.get("search") as string | undefined) ?? "";
  const projectId = (filter.get("project_id__eq") as string | undefined) ?? "";
  const siteId =
    (filter.get("primary_site_id__eq") as string | undefined) ?? "";
  const recorderId =
    (filter.get("primary_recorder_id__eq") as string | undefined) ?? "";
  const visibility =
    (filter.get("visibility__eq") as VisibilityFilterValue | undefined) ?? "";

  const {
    projectOptions,
    siteOptions,
    recorderOptions,
  } = useDatasetFilterOptions({ projectId });

  const hasActiveFilters =
    Boolean(projectId || siteId || recorderId || visibility || searchValue);

  const handleProjectChange = (value: string) => {
    if (value) {
      filter.set("project_id__eq", value);
    } else {
      filter.clear("project_id__eq");
    }
    filter.clear("primary_site_id__eq");
    filter.submit();
  };

  const handleSiteChange = (value: string) => {
    if (value) {
      filter.set("primary_site_id__eq", value);
    } else {
      filter.clear("primary_site_id__eq");
    }
    filter.submit();
  };

  const handleRecorderChange = (value: string) => {
    if (value) {
      filter.set("primary_recorder_id__eq", value);
    } else {
      filter.clear("primary_recorder_id__eq");
    }
    filter.submit();
  };

  const handleVisibilityChange = (value: VisibilityFilterValue) => {
    if (value) {
      filter.set("visibility__eq", value);
    } else {
      filter.clear("visibility__eq");
    }
    filter.submit();
  };

  const handleClearFilters = () => {
    filter.reset();
    filter.submit();
  };

  return (
    <DatasetListBase
      datasets={items}
      isLoading={isLoading}
      onClickDataset={onClickDataset}
      DatasetImport={<DatasetImport onImportDataset={onCreateDataset} />}
      DatasetSearch={
        <div className="flex flex-col gap-3">
          <Search
            label="Search"
            placeholder="Search datasets..."
            value={searchValue}
            onChange={(value) =>
              filter.set(
                "search",
                (value as string).trim() === "" ? undefined : (value as string),
              )
            }
            onSubmit={filter.submit}
            icon={<AnnotationProjectIcon />}
          />
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            <Select
              label="Project"
              options={projectOptions}
              selected={
                projectOptions.find(
                  (option) => option.value === projectId,
                ) ?? projectOptions[0]!
              }
              onChange={handleProjectChange}
              placement="bottom-start"
            />
            <Select
              label="Site"
              options={siteOptions}
              selected={
                siteOptions.find((option) => option.value === siteId) ??
                siteOptions[0]!
              }
              onChange={handleSiteChange}
              placement="bottom-start"
            />
            <Select
              label="Recorder"
              options={recorderOptions}
              selected={
                recorderOptions.find(
                  (option) => option.value === recorderId,
                ) ?? recorderOptions[0]!
              }
              onChange={handleRecorderChange}
              placement="bottom-start"
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <VisibilityFilterChips
              value={visibility}
              onChange={handleVisibilityChange}
            />
            <Button
              mode="text"
              variant="secondary"
              padding="px-2 py-1"
              disabled={!hasActiveFilters}
              onClick={handleClearFilters}
            >
              Clear filters
            </Button>
          </div>
        </div>
      }
      DatasetCreate={
        <DatasetCreate
          onCreateDataset={onCreateDataset}
          defaultProjectId={projectId || undefined}
        />
      }
      Pagination={<Pagination pagination={pagination} />}
    />
  );
}
