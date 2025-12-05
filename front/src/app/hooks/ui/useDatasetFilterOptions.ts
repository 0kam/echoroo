import { useMemo } from "react";

import {
  useMetadataLicenses,
  useMetadataProjects,
  useMetadataRecorders,
  useMetadataSites,
} from "@/app/hooks/api/useMetadata";

import type { Option } from "@/lib/components/inputs/Select";

type UseDatasetFilterOptionsArgs = {
  projectId: string;
  includeLicenses?: boolean;
};

type DatasetFilterOptions = {
  projectOptions: Option<string>[];
  siteOptions: Option<string>[];
  recorderOptions: Option<string>[];
  licenseOptions?: Option<string>[];
  queries: {
    projects: ReturnType<typeof useMetadataProjects>["query"];
    sites: ReturnType<typeof useMetadataSites>["query"];
    recorders: ReturnType<typeof useMetadataRecorders>["query"];
    licenses?: ReturnType<typeof useMetadataLicenses>["query"];
  };
};

function formatOptionLabel(primary: string, secondary?: string | null) {
  if (!secondary || primary === secondary) {
    return primary;
  }
  return `${primary} (${secondary})`;
}

function ensureBaseOption(
  id: string,
  baseLabel: string,
  isLoading: boolean,
): Option<string> {
  return {
    id,
    label: isLoading ? `${baseLabel}…` : baseLabel,
    value: "",
    disabled: isLoading,
  };
}

export default function useDatasetFilterOptions({
  projectId,
  includeLicenses = false,
}: UseDatasetFilterOptionsArgs): DatasetFilterOptions {
  const projects = useMetadataProjects();
  const sites = useMetadataSites(
    useMemo(() => ({ project_id: projectId || undefined }), [projectId]),
  );
  const recorders = useMetadataRecorders();
  const licenses = useMetadataLicenses();

  const projectOptions = useMemo<Option<string>[]>(() => {
    const items = projects.query.data ?? [];
    const base = ensureBaseOption(
      "project-all",
      "All projects",
      projects.query.isLoading && items.length === 0,
    );

    if (items.length === 0) {
      return [base];
    }

    return [
      { ...base, disabled: false, label: "All projects" },
      ...items.map((project) => ({
        id: project.project_id,
        label: formatOptionLabel(
          project.project_name,
          project.project_id,
        ),
        value: project.project_id,
      })),
    ];
  }, [projects.query.data, projects.query.isLoading]);

  const siteOptions = useMemo<Option<string>[]>(() => {
    const items = sites.query.data ?? [];
    const base = ensureBaseOption(
      "site-all",
      projectId ? "All sites" : "All sites",
      sites.query.isLoading && items.length === 0,
    );

    if (items.length === 0) {
      return [base];
    }

    return [
      {
        ...base,
        disabled: false,
        label: projectId ? "All sites" : "All sites",
      },
      ...items.map((site) => ({
        id: site.site_id,
        label: formatOptionLabel(site.site_name, site.site_id),
        value: site.site_id,
      })),
    ];
  }, [projectId, sites.query.data, sites.query.isLoading]);

  const recorderOptions = useMemo<Option<string>[]>(() => {
    const items = recorders.query.data ?? [];
    const base = ensureBaseOption(
      "recorder-all",
      "All recorders",
      recorders.query.isLoading && items.length === 0,
    );

    if (items.length === 0) {
      return [base];
    }

    return [
      { ...base, disabled: false, label: "All recorders" },
      ...items.map((recorder) => ({
        id: recorder.recorder_id,
        label: formatOptionLabel(
          recorder.recorder_name,
          recorder.recorder_id,
        ),
        value: recorder.recorder_id,
      })),
    ];
  }, [recorders.query.data, recorders.query.isLoading]);

  const licenseOptions = useMemo<Option<string>[]>(() => {
    if (!includeLicenses) {
      return [];
    }

    const items = licenses.query.data ?? [];
    const base = ensureBaseOption(
      "license-all",
      "All licenses",
      licenses.query.isLoading && items.length === 0,
    );

    if (items.length === 0) {
      return [base];
    }

    return [
      { ...base, disabled: false, label: "All licenses" },
      ...items.map((license) => ({
        id: license.license_id,
        label: formatOptionLabel(
          license.license_name,
          license.license_id,
        ),
        value: license.license_id,
      })),
    ];
  }, [includeLicenses, licenses.query.data, licenses.query.isLoading]);

  return {
    projectOptions,
    siteOptions,
    recorderOptions,
    licenseOptions: includeLicenses ? licenseOptions : undefined,
    queries: {
      projects: projects.query,
      sites: sites.query,
      recorders: recorders.query,
      licenses: includeLicenses ? licenses.query : undefined,
    },
  };
}
