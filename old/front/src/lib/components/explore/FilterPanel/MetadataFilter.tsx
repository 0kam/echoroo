"use client";

import { useMemo } from "react";

import useDatasetFilterOptions from "@/app/hooks/ui/useDatasetFilterOptions";
import { Group, Select } from "@/lib/components/inputs";

type MetadataFilterProps = {
  projectIds: string[];
  siteIds: string[];
  recorderIds: string[];
  onProjectChange: (projectId: string) => void;
  onSiteChange: (siteId: string) => void;
  onRecorderChange: (recorderId: string) => void;
};

export default function MetadataFilter({
  projectIds,
  siteIds,
  recorderIds,
  onProjectChange,
  onSiteChange,
  onRecorderChange,
}: MetadataFilterProps) {
  const currentProjectId = projectIds[0] ?? "";

  const { projectOptions, siteOptions, recorderOptions } =
    useDatasetFilterOptions({ projectId: currentProjectId });

  const defaultOption = { value: "", label: "All" };

  const selectedProject = useMemo(
    () =>
      projectOptions.find((opt) => opt.value === currentProjectId) ??
      projectOptions[0] ??
      defaultOption,
    [projectOptions, currentProjectId],
  );

  const currentSiteId = siteIds[0] ?? "";
  const selectedSite = useMemo(
    () =>
      siteOptions.find((opt) => opt.value === currentSiteId) ??
      siteOptions[0] ??
      defaultOption,
    [siteOptions, currentSiteId],
  );

  const currentRecorderId = recorderIds[0] ?? "";
  const selectedRecorder = useMemo(
    () =>
      recorderOptions.find((opt) => opt.value === currentRecorderId) ??
      recorderOptions[0] ??
      defaultOption,
    [recorderOptions, currentRecorderId],
  );

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium text-stone-700 dark:text-stone-300">
        Metadata
      </h4>

      <Group label="Project" name="project_filter">
        <Select
          label="Project"
          options={projectOptions}
          selected={selectedProject}
          onChange={onProjectChange}
          placement="bottom-start"
        />
      </Group>

      <Group label="Site" name="site_filter">
        <Select
          label="Site"
          options={siteOptions}
          selected={selectedSite}
          onChange={onSiteChange}
          placement="bottom-start"
        />
      </Group>

      <Group label="Recorder" name="recorder_filter">
        <Select
          label="Recorder"
          options={recorderOptions}
          selected={selectedRecorder}
          onChange={onRecorderChange}
          placement="bottom-start"
        />
      </Group>
    </div>
  );
}
