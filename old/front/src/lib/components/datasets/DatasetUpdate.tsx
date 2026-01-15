import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";
import useActiveUser from "@/app/hooks/api/useActiveUser";

import { Select } from "@/lib/components/inputs";
import type { Option } from "@/lib/components/inputs/Select";
import Card from "@/lib/components/ui/Card";
import Description, {
  DescriptionData,
  DescriptionTerm,
} from "@/lib/components/ui/Description";
import VisibilityBadge from "@/lib/components/ui/VisibilityBadge";

import { DatasetUpdateSchema, VisibilityLevel } from "@/lib/schemas";
import type {
  Dataset,
  DatasetUpdate,
  License,
  Project,
  Recorder,
  Site,
} from "@/lib/types";

const VISIBILITY_OPTIONS: Option<VisibilityLevel>[] = [
  {
    id: "public",
    label: "🌍 Public – Visible to all authenticated users",
    value: "public",
  },
  {
    id: "restricted",
    label: "🔒 Restricted – Project members and managers",
    value: "restricted",
  },
];

function wrapUpdate(update: Partial<DatasetUpdate>): DatasetUpdate {
  return DatasetUpdateSchema.parse(update);
}

export default function DatasetUpdateComponent({
  dataset,
  onChangeDataset,
}: {
  dataset: Dataset;
  onChangeDataset?: (dataset: DatasetUpdate) => void;
}) {
  const { data: activeUser } = useActiveUser();

  const {
    data: projects = [],
  } = useQuery<Project[]>({
    queryKey: ["metadata", "projects", "all"],
    queryFn: () => api.metadata.projects.list({ is_active: true }),
    staleTime: 60_000,
  });

  const {
    data: sites = [],
  } = useQuery<Site[]>({
    queryKey: ["metadata", "sites", "all"],
    queryFn: () => api.metadata.sites.list(),
    staleTime: 60_000,
  });

  const {
    data: recorders = [],
  } = useQuery<Recorder[]>({
    queryKey: ["metadata", "recorders", "all"],
    queryFn: () => api.metadata.recorders.list(),
    staleTime: 60_000,
  });

  const {
    data: licenses = [],
  } = useQuery<License[]>({
    queryKey: ["metadata", "licenses", "all"],
    queryFn: () => api.metadata.licenses.list(),
    staleTime: 60_000,
  });

  const isProjectManager = useMemo(() => {
    if (!activeUser) return false;
    if (activeUser.is_superuser) return true;
    const memberships = dataset.project?.memberships ?? [];
    return memberships.some(
      (membership) =>
        membership.user_id === activeUser.id &&
        membership.role === "manager",
    );
  }, [activeUser, dataset.project]);

  const canEditMetadata = Boolean(activeUser && (activeUser.is_superuser || isProjectManager));

  const availableProjects = useMemo(() => {
    if (!projects.length) return dataset.project ? [dataset.project] : [];
    if (activeUser?.is_superuser) {
      return projects;
    }
    if (!activeUser) return dataset.project ? [dataset.project] : [];
    const managed = projects.filter((project) =>
      project.memberships.some(
        (membership) =>
          membership.user_id === activeUser.id &&
          membership.role === "manager",
      ),
    );
    const lookup = new Map(managed.map((project) => [project.project_id, project]));
    if (dataset.project && !lookup.has(dataset.project.project_id)) {
      lookup.set(dataset.project.project_id, dataset.project);
    }
    return Array.from(lookup.values());
  }, [projects, dataset.project, activeUser]);

  const projectOptions: Option<string>[] = useMemo(() => {
    return availableProjects.map((project) => ({
      id: project.project_id,
      label: (
        <div className="flex flex-col">
          <span className="font-medium text-stone-900 dark:text-stone-100">
            {project.project_name}
          </span>
          <span className="text-xs text-stone-500 dark:text-stone-400">
            {project.project_id}
          </span>
        </div>
      ),
      value: project.project_id,
    }));
  }, [availableProjects]);

  const selectedProjectOption =
    projectOptions.find((option) => option.value === dataset.project_id) ??
    (dataset.project
      ? {
          id: dataset.project.project_id,
          label: dataset.project.project_name,
          value: dataset.project.project_id,
        }
      : {
          id: dataset.project_id,
          label: dataset.project_id,
          value: dataset.project_id,
        });

  const projectSites = useMemo(() => {
    const filtered = sites.filter(
      (site) => site.project_id === dataset.project_id,
    );
    const lookup = new Map(filtered.map((site) => [site.site_id, site]));
    if (dataset.primary_site && !lookup.has(dataset.primary_site.site_id)) {
      lookup.set(dataset.primary_site.site_id, dataset.primary_site);
    }
    return Array.from(lookup.values());
  }, [sites, dataset]);

  const siteOptions: Option<string | null>[] = useMemo(() => {
    return [
      {
        id: "site-none",
        label: "No primary site",
        value: null,
      },
      ...projectSites.map((site) => ({
        id: site.site_id,
        label: `${site.site_name} (${site.site_id})`,
        value: site.site_id,
      })),
    ];
  }, [projectSites]);

  const selectedSiteOption =
    siteOptions.find((option) => option.value === dataset.primary_site_id) ??
    siteOptions[0];

  const recorderOptions: Option<string | null>[] = useMemo(() => {
    const lookup = new Map(recorders.map((recorder) => [recorder.recorder_id, recorder]));
    if (
      dataset.primary_recorder &&
      !lookup.has(dataset.primary_recorder.recorder_id)
    ) {
      lookup.set(
        dataset.primary_recorder.recorder_id,
        dataset.primary_recorder,
      );
    }
    return [
      { id: "recorder-none", label: "No primary recorder", value: null },
      ...Array.from(lookup.values()).map((recorder) => ({
        id: recorder.recorder_id,
        label: `${recorder.recorder_name} (${recorder.recorder_id})`,
        value: recorder.recorder_id,
      })),
    ];
  }, [recorders, dataset.primary_recorder]);

  const selectedRecorderOption =
    recorderOptions.find(
      (option) => option.value === dataset.primary_recorder_id,
    ) ?? recorderOptions[0];

  const licenseOptions: Option<string | null>[] = useMemo(() => {
    const lookup = new Map(licenses.map((license) => [license.license_id, license]));
    if (dataset.license && !lookup.has(dataset.license.license_id)) {
      lookup.set(dataset.license.license_id, dataset.license);
    }
    return [
      { id: "license-none", label: "No license specified", value: null },
      ...Array.from(lookup.values()).map((license) => ({
        id: license.license_id,
        label: `${license.license_name} (${license.license_id})`,
        value: license.license_id,
      })),
    ];
  }, [licenses, dataset.license]);

  const selectedLicenseOption =
    licenseOptions.find((option) => option.value === dataset.license_id) ??
    licenseOptions[0];

  const selectedVisibilityOption =
    VISIBILITY_OPTIONS.find((option) => option.value === dataset.visibility) ??
    VISIBILITY_OPTIONS[1];

  const handleProjectChange = (value: string) => {
    if (!canEditMetadata || !value || value === dataset.project_id) return;
    const update: DatasetUpdate = {
      project_id: value,
    };
    if (dataset.primary_site_id) {
      update.primary_site_id = null;
    }
    onChangeDataset?.(wrapUpdate(update));
  };

  const handleSiteChange = (value: string | null) => {
    if (!canEditMetadata) return;
    onChangeDataset?.(wrapUpdate({ primary_site_id: value }));
  };

  const handleRecorderChange = (value: string | null) => {
    if (!canEditMetadata) return;
    onChangeDataset?.(wrapUpdate({ primary_recorder_id: value }));
  };

  const handleLicenseChange = (value: string | null) => {
    if (!canEditMetadata) return;
    onChangeDataset?.(wrapUpdate({ license_id: value }));
  };

  const handleVisibilityChange = (value: VisibilityLevel) => {
    if (!canEditMetadata || value === dataset.visibility) return;
    onChangeDataset?.(wrapUpdate({ visibility: value }));
  };

  const handleFieldChange = (
    field: keyof DatasetUpdate,
    value: string | null,
  ) => {
    if (!canEditMetadata) return;
    onChangeDataset?.(wrapUpdate({ [field]: value ?? undefined }));
  };

  const handleGainChange = (value: string) => {
    if (!canEditMetadata) return;
    const parsed = value ? parseFloat(value) : null;
    const gain = parsed !== null && !isNaN(parsed) ? parsed : null;
    onChangeDataset?.(wrapUpdate({ gain }));
  };

  return (
    <Card>
      <div className="px-4 sm:px-0 space-y-1">
        <h3 className="text-base font-semibold leading-7 text-stone-900 dark:text-stone-200">
          Dataset Information
        </h3>
        {!canEditMetadata ? (
          <p className="text-sm text-stone-500 dark:text-stone-400">
            Only project managers or superusers can edit metadata.
          </p>
        ) : null}
      </div>
      <div className="mt-6 border-t border-stone-300 dark:border-stone-700">
        <dl className="divide-y divide-stone-200 dark:divide-stone-700">
          <div className="py-6 px-4 sm:px-0">
            <Description
              name="Name"
              value={dataset.name}
              onChange={(value) => handleFieldChange("name", value)}
              type="text"
              editable={canEditMetadata}
            />
          </div>
          <div className="py-6 px-4 sm:px-0">
            <Description
              name="Description"
              value={dataset.description ?? ""}
              onChange={(value) => handleFieldChange("description", value)}
              type="textarea"
              editable={canEditMetadata}
            />
          </div>
          <div className="py-6 px-4 sm:px-0">
            <Description
              name="Notes"
              value={dataset.note ?? ""}
              onChange={(value) => handleFieldChange("note", value)}
              type="textarea"
              editable={canEditMetadata}
            />
          </div>
          <div className="py-6 px-4 sm:px-0">
            <Description
              name="DOI"
              value={dataset.doi ?? ""}
              onChange={(value) => handleFieldChange("doi", value)}
              type="text"
              editable={canEditMetadata}
            />
          </div>
          <div className="py-6 px-4 sm:px-0">
            <Description
              name="Created On"
              value={dataset.created_on}
              type="date"
              editable={false}
            />
          </div>
          <div className="py-6 px-4 sm:px-0 overflow-hidden">
            <DescriptionTerm>Visibility</DescriptionTerm>
            <DescriptionData>
              <div className="flex flex-col gap-3">
                <VisibilityBadge visibility={dataset.visibility} />
                {canEditMetadata ? (
                  <div className="max-w-sm">
                    <Select
                      options={VISIBILITY_OPTIONS}
                      selected={selectedVisibilityOption}
                      onChange={handleVisibilityChange}
                    />
                  </div>
                ) : null}
              </div>
            </DescriptionData>
          </div>
          <div className="py-6 px-4 sm:px-0">
            <DescriptionTerm>Project</DescriptionTerm>
            <DescriptionData>
              {canEditMetadata && projectOptions.length > 0 ? (
                <Select
                  label="Project"
                  options={projectOptions}
                  selected={selectedProjectOption}
                  onChange={handleProjectChange}
                  placement="bottom-start"
                />
              ) : (
                <span className="text-sm text-stone-700 dark:text-stone-300">
                  {dataset.project?.project_name ?? dataset.project_id}
                </span>
              )}
            </DescriptionData>
          </div>
          <div className="py-6 px-4 sm:px-0">
            <DescriptionTerm>Primary Site</DescriptionTerm>
            <DescriptionData>
              {canEditMetadata ? (
                <Select
                  label="Site"
                  options={siteOptions}
                  selected={selectedSiteOption}
                  onChange={handleSiteChange}
                  placement="bottom-start"
                />
              ) : (
                <span className="text-sm text-stone-700 dark:text-stone-300">
                  {dataset.primary_site
                    ? `${dataset.primary_site.site_name} (${dataset.primary_site.site_id})`
                    : "—"}
                </span>
              )}
            </DescriptionData>
          </div>
          <div className="py-6 px-4 sm:px-0">
            <DescriptionTerm>Primary Recorder</DescriptionTerm>
            <DescriptionData>
              {canEditMetadata ? (
                <Select
                  label="Recorder"
                  options={recorderOptions}
                  selected={selectedRecorderOption}
                  onChange={handleRecorderChange}
                  placement="bottom-start"
                />
              ) : (
                <span className="text-sm text-stone-700 dark:text-stone-300">
                  {dataset.primary_recorder
                    ? `${dataset.primary_recorder.recorder_name} (${dataset.primary_recorder.recorder_id})`
                    : "—"}
                </span>
              )}
            </DescriptionData>
          </div>
          <div className="py-6 px-4 sm:px-0">
            <DescriptionTerm>License</DescriptionTerm>
            <DescriptionData>
              {canEditMetadata ? (
                <Select
                  label="License"
                  options={licenseOptions}
                  selected={selectedLicenseOption}
                  onChange={handleLicenseChange}
                  placement="bottom-start"
                />
              ) : (
                <span className="text-sm text-stone-700 dark:text-stone-300">
                  {dataset.license
                    ? `${dataset.license.license_name} (${dataset.license.license_id})`
                    : "—"}
                </span>
              )}
            </DescriptionData>
          </div>
          <div className="py-6 px-4 sm:px-0">
            <DescriptionTerm>Gain (dB)</DescriptionTerm>
            <DescriptionData>
              {canEditMetadata ? (
                <input
                  type="number"
                  step="0.1"
                  value={dataset.gain ?? ""}
                  onChange={(e) => handleGainChange(e.target.value)}
                  placeholder="e.g., 12.0"
                  className="block w-full max-w-xs rounded-md border-stone-300 shadow-sm focus:border-amber-500 focus:ring-amber-500 sm:text-sm dark:bg-stone-800 dark:border-stone-600 dark:text-stone-200"
                />
              ) : (
                <span className="text-sm text-stone-700 dark:text-stone-300">
                  {dataset.gain != null ? `${dataset.gain} dB` : "—"}
                </span>
              )}
            </DescriptionData>
          </div>
        </dl>
      </div>
    </Card>
  );
}
