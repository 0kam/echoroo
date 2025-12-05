import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import api from "@/app/api";
import useActiveUser from "@/app/hooks/api/useActiveUser";
import { useMetadataSites } from "@/app/hooks/api/useMetadata";

import {
  Group,
  Input,
  Select,
  Submit,
  TextArea,
} from "@/lib/components/inputs";
import type { Option } from "@/lib/components/inputs/Select";
import { DatasetCreateSchema, VisibilityLevel } from "@/lib/schemas";
import type {
  DatasetCandidate,
  DatasetCandidateInfo,
  DatasetCreate,
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

/**
 * Component for creating a new dataset.
 */
export default function CreateDataset({
  onCreateDataset,
  defaultProjectId,
}: {
  onCreateDataset?: (dataset: DatasetCreate) => void;
  defaultProjectId?: string;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
    setValue,
    watch,
  } = useForm<DatasetCreate>({
    resolver: zodResolver(DatasetCreateSchema),
    mode: "onChange",
    defaultValues: {
      audio_dir: "",
      visibility: "restricted",
      project_id: defaultProjectId ?? "",
      primary_site_id: null,
      primary_recorder_id: null,
      license_id: null,
      name: "",
      description: "",
      doi: "",
      note: "",
      gain: null,
    },
  });

  useEffect(() => {
    register("visibility");
    register("audio_dir");
    register("project_id");
    register("primary_site_id");
    register("primary_recorder_id");
    register("license_id");
    register("doi");
    register("note");
  }, [register]);

  const audioDirValue = watch("audio_dir");
  const visibility = watch("visibility");
  const projectId = watch("project_id");
  const primarySiteId = watch("primary_site_id");
  const primaryRecorderId = watch("primary_recorder_id");
  const licenseId = watch("license_id");
  useEffect(() => {
    if (!defaultProjectId) return;
    if (projectId === defaultProjectId) return;
    setValue("project_id", defaultProjectId, { shouldValidate: true });
    setValue("primary_site_id", null, { shouldValidate: true });
  }, [defaultProjectId, projectId, setValue]);

  const {
    data: candidates = [],
    isLoading: candidatesLoading,
    refetch: refetchCandidates,
    error: candidatesError,
  } = useQuery<DatasetCandidate[]>({
    queryKey: ["dataset-candidates"],
    queryFn: api.datasets.getCandidates,
  });

  const [searchTerm, setSearchTerm] = useState("");
  const [selectedCandidate, setSelectedCandidate] =
    useState<DatasetCandidate | null>(null);
  const [candidateInfo, setCandidateInfo] =
    useState<DatasetCandidateInfo | null>(null);
  const [inspectError, setInspectError] = useState<string | null>(null);
  const [isInspecting, setIsInspecting] = useState(false);

  useEffect(() => {
    if (!selectedCandidate) return;
    const stillPresent = candidates.some(
      (candidate) =>
        candidate.relative_path === selectedCandidate.relative_path,
    );
    if (!stillPresent) {
      setSelectedCandidate(null);
      setCandidateInfo(null);
      setInspectError(null);
      setSearchTerm("");
      setValue("audio_dir", "", { shouldValidate: true });
    }
  }, [candidates, selectedCandidate, setValue]);

  const filteredCandidates = useMemo(() => {
    if (!candidates.length) return [] as DatasetCandidate[];
    const normalized = searchTerm.trim().toLowerCase();
    if (!normalized) return candidates;
    return candidates.filter((candidate) =>
      candidate.relative_path.toLowerCase().includes(normalized) ||
      candidate.name.toLowerCase().includes(normalized),
    );
  }, [candidates, searchTerm]);

  const candidatePlaceholder: Option<string> = useMemo(
    () => ({
      id: "placeholder",
      label: candidatesLoading
        ? "Loading directories…"
        : "Select a directory",
      value: "",
      disabled: true,
    }),
    [candidatesLoading],
  );

  const candidateOptions: Option<string>[] = useMemo(
    () => [
      candidatePlaceholder,
      ...filteredCandidates.map((candidate) => ({
        id: candidate.relative_path,
        label: candidate.relative_path,
        value: candidate.relative_path,
      })),
    ],
    [filteredCandidates, candidatePlaceholder],
  );

  const selectedCandidateOption: Option<string> = selectedCandidate
    ? {
        id: selectedCandidate.relative_path,
        label: selectedCandidate.relative_path,
        value: selectedCandidate.relative_path,
      }
    : candidatePlaceholder;

  const handleCandidateChange = useCallback(
    (relativePath: string) => {
      if (!relativePath) return;
      const candidate = candidates.find(
        (item) => item.relative_path === relativePath,
      );
      if (!candidate) return;
      setSelectedCandidate(candidate);
      setValue("audio_dir", candidate.absolute_path, {
        shouldValidate: true,
        shouldDirty: true,
      });
      setCandidateInfo(null);
      setInspectError(null);
      setIsInspecting(true);
      void api.datasets
        .inspectCandidate(candidate.relative_path)
        .then((info) => {
          setCandidateInfo(info);
          setIsInspecting(false);
        })
        .catch((error: unknown) => {
          const message =
            (error as { response?: { data?: { message?: string } } })
              ?.response?.data?.message ??
            (error instanceof Error ? error.message : undefined) ??
            "Failed to inspect directory.";
          setInspectError(message);
          setCandidateInfo(null);
          setIsInspecting(false);
        });
    },
    [candidates, setValue],
  );

  const handleRefreshCandidates = useCallback(() => {
    void refetchCandidates();
  }, [refetchCandidates]);

  const hasAudioFiles = candidateInfo?.audio_file_count
    ? candidateInfo.audio_file_count > 0
    : false;

  const audioDirError =
    errors.audio_dir?.message ??
    inspectError ??
    (!isInspecting && candidateInfo && !hasAudioFiles
      ? "No audio files were found in the selected directory."
      : undefined);

  const candidatesErrorMessage =
    candidatesError instanceof Error ? candidatesError.message : undefined;

  const { data: activeUser } = useActiveUser();

  const {
    data: projects = [],
    isLoading: projectsLoading,
    error: projectsError,
  } = useQuery<Project[]>({
    queryKey: ["metadata", "projects", "all"],
    queryFn: () => api.metadata.projects.list({ is_active: true }),
    staleTime: 60_000,
  });

  const siteQueryArgs = useMemo(
    () => ({
      project_id: projectId || undefined,
    }),
    [projectId],
  );
  const { query: siteQuery } = useMetadataSites(siteQueryArgs);
  const sitesData = siteQuery.data ?? [];
  const sitesLoading = siteQuery.isLoading;
  const sitesErrorMessage =
    siteQuery.error instanceof Error ? siteQuery.error.message : undefined;

  const {
    data: recorders = [],
    isLoading: recordersLoading,
  } = useQuery<Recorder[]>({
    queryKey: ["metadata", "recorders", "all"],
    queryFn: () => api.metadata.recorders.list(),
    staleTime: 60_000,
  });

  const {
    data: licenses = [],
    isLoading: licensesLoading,
  } = useQuery<License[]>({
    queryKey: ["metadata", "licenses", "all"],
    queryFn: () => api.metadata.licenses.list(),
    staleTime: 60_000,
  });

  const availableProjects = useMemo(() => {
    if (!projects.length) return [] as Project[];
    if (activeUser?.is_superuser) {
      return projects;
    }
    if (!activeUser) return [];
    return projects.filter((project) =>
      project.memberships.some(
        (membership) =>
          membership.user_id === activeUser.id &&
          membership.role === "manager",
      ),
    );
  }, [projects, activeUser]);

  const projectOptions: Option<string>[] = useMemo(() => {
    const placeholder: Option<string> = {
      id: "project-placeholder",
      label: projectsLoading
        ? "Loading projects…"
        : availableProjects.length === 0
          ? "No manageable projects"
          : "Select a project",
      value: "",
      disabled: true,
    };
    const options = availableProjects.map((project) => ({
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
    return [placeholder, ...options];
  }, [availableProjects, projectsLoading]);

  const selectedProjectOption =
    projectOptions.find((option) => option.value === projectId) ??
    projectOptions[0];

  const selectedProject = useMemo(
    () => availableProjects.find((project) => project.project_id === projectId),
    [availableProjects, projectId],
  );

  const projectLoadError =
    projectsError instanceof Error ? projectsError.message : undefined;

  const projectHelpMessage =
    !projectsLoading && availableProjects.length === 0
      ? "You must be a project manager (or superuser) to register new datasets. Ask an administrator to add you as a manager."
      : "Datasets belong to a project. Choose one to continue.";

  const projectSites = useMemo(() => {
    if (!projectId) {
      return [] as Site[];
    }
    return sitesData.filter((site) => site.project_id === projectId);
  }, [projectId, sitesData]);

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
    siteOptions.find(
      (option) =>
        option.value === (primarySiteId == null ? null : primarySiteId),
    ) ?? siteOptions[0];

  const recorderOptions: Option<string | null>[] = useMemo(
    () => [
      {
        id: "recorder-none",
        label: "No primary recorder",
        value: null,
      },
      ...recorders.map((recorder) => ({
        id: recorder.recorder_id,
        label: `${recorder.recorder_name} (${recorder.recorder_id})`,
        value: recorder.recorder_id,
      })),
    ],
    [recorders],
  );

  const selectedRecorderOption =
    recorderOptions.find(
      (option) =>
        option.value === (primaryRecorderId == null ? null : primaryRecorderId),
    ) ?? recorderOptions[0];

  const licenseOptions: Option<string | null>[] = useMemo(
    () => [
      {
        id: "license-none",
        label: "No license specified",
        value: null,
      },
      ...licenses.map((license) => ({
        id: license.license_id,
        label: `${license.license_name} (${license.license_id})`,
        value: license.license_id,
      })),
    ],
    [licenses],
  );

  const selectedLicenseOption =
    licenseOptions.find(
      (option) =>
        option.value === (licenseId == null ? null : licenseId),
    ) ?? licenseOptions[0];

  const selectedVisibility =
    VISIBILITY_OPTIONS.find((option) => option.value === visibility) ??
    VISIBILITY_OPTIONS[1];

  const isManagerForSelectedProject = useMemo(() => {
    if (!selectedProject) return false;
    if (activeUser?.is_superuser) return true;
    if (!activeUser) return false;
    return selectedProject.memberships.some(
      (membership) =>
        membership.user_id === activeUser.id &&
        membership.role === "manager",
    );
  }, [selectedProject, activeUser]);

  const handleVisibilityChange = useCallback(
    (value: VisibilityLevel) => {
      setValue("visibility", value, { shouldValidate: true });
    },
    [setValue],
  );

  const handleProjectChange = useCallback(
    (value: string) => {
      setValue("project_id", value, {
        shouldValidate: true,
        shouldDirty: true,
      });
      setValue("primary_site_id", null, {
        shouldValidate: true,
        shouldDirty: true,
      });
    },
    [setValue],
  );

  const handleSiteChange = useCallback(
    (value: string | null) => {
      setValue("primary_site_id", value, {
        shouldValidate: true,
        shouldDirty: true,
      });
    },
    [setValue],
  );

  const handleRecorderChange = useCallback(
    (value: string | null) => {
      setValue("primary_recorder_id", value, {
        shouldValidate: true,
        shouldDirty: true,
      });
    },
    [setValue],
  );

  const handleLicenseChange = useCallback(
    (value: string | null) => {
      setValue("license_id", value, {
        shouldValidate: true,
        shouldDirty: true,
      });
    },
    [setValue],
  );

  const canCreateRestricted =
    visibility !== "restricted" || isManagerForSelectedProject;

  const canSubmit =
    canCreateRestricted &&
    !!projectId &&
    !!selectedCandidate &&
    !!candidateInfo &&
    hasAudioFiles &&
    !isInspecting &&
    !audioDirError;

  const onSubmit = useCallback(
    (data: DatasetCreate) => {
      if (!canSubmit) return;
      onCreateDataset?.(data);
    },
    [canSubmit, onCreateDataset],
  );

  return (
    <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)}>
      <div className="grid gap-4 md:grid-cols-2">
        <Group
          name="name"
          label="Name"
          help="Provide a clear, human-friendly dataset name."
          error={errors.name?.message}
        >
          <Input {...register("name")} />
        </Group>
        <Group
          name="project_id"
          label="Project"
          help={projectHelpMessage}
          error={errors.project_id?.message ?? projectLoadError}
        >
          <Select
            label="Project"
            options={projectOptions}
            selected={selectedProjectOption}
            onChange={handleProjectChange}
            placement="bottom-start"
          />
        </Group>
      </div>

      <Group
        name="description"
        label="Description"
        help="Describe the recording campaign, location, or objectives."
        error={errors.description?.message}
      >
        <TextArea rows={3} {...register("description")} />
      </Group>

      <div className="grid gap-4 md:grid-cols-2">
        <Group
          name="primary_site_id"
          label="Primary Site"
        help={
          projectId
            ? projectSites.length === 0
              ? "No sites are registered for this project yet."
              : "Optional. Choose the site most recordings belong to."
            : "Select a project to choose from its sites."
        }
        error={errors.primary_site_id?.message ?? sitesErrorMessage}
        >
          <Select
            label={sitesLoading ? "Loading sites…" : "Site"}
            options={siteOptions}
            selected={selectedSiteOption}
            onChange={handleSiteChange}
            placement="bottom-start"
          />
        </Group>
        <Group
          name="primary_recorder_id"
          label="Primary Recorder"
          help="Optional. Recorder model most commonly used."
          error={errors.primary_recorder_id?.message}
        >
          <Select
            label={recordersLoading ? "Loading recorders…" : "Recorder"}
            options={recorderOptions}
            selected={selectedRecorderOption}
            onChange={handleRecorderChange}
            placement="bottom-start"
          />
        </Group>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Group
          name="license_id"
          label="License"
          help="Optional. Apply a usage license to all recordings."
          error={errors.license_id?.message}
        >
          <Select
            label={licensesLoading ? "Loading licenses…" : "License"}
            options={licenseOptions}
            selected={selectedLicenseOption}
            onChange={handleLicenseChange}
            placement="bottom-start"
          />
        </Group>
        <Group
          name="doi"
          label="DOI"
          help="Optional. Provide a DOI if the dataset is published."
          error={errors.doi?.message}
        >
          <Input
            placeholder="10.1234/example.dataset"
            {...register("doi")}
          />
        </Group>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Group
          name="gain"
          label="Gain (dB)"
          help="Optional. Recorder gain setting in decibels."
          error={errors.gain?.message}
        >
          <Input
            type="number"
            step="0.1"
            placeholder="e.g., 12.0"
            {...register("gain", { valueAsNumber: true })}
          />
        </Group>
      </div>

      <Group
        name="note"
        label="Notes"
        help="Optional. Internal notes visible to project members."
        error={errors.note?.message}
      >
        <TextArea rows={3} {...register("note")} />
      </Group>

      <Group
        name="audio_dir"
        label="Audio Directory"
        help="Choose a subdirectory from the audio root."
        error={audioDirError}
      >
        <div className="flex flex-col gap-2">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <Input
              type="text"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="Search directories…"
            />
            <button
              type="button"
              onClick={handleRefreshCandidates}
              className="text-sm text-amber-600 underline underline-offset-2 disabled:text-stone-400"
              disabled={candidatesLoading}
            >
              Refresh list
            </button>
          </div>
          {candidatesLoading ? (
            <p className="text-sm text-stone-500">Loading directories…</p>
          ) : candidatesErrorMessage ? (
            <p className="text-sm text-rose-600">
              Failed to load directories.
              {candidatesErrorMessage ? ` ${candidatesErrorMessage}` : ""}
            </p>
          ) : candidates.length === 0 ? (
            <p className="text-sm text-stone-500">
              No subdirectories were found. Upload audio and refresh this list.
            </p>
          ) : filteredCandidates.length === 0 ? (
            <p className="text-sm text-stone-500">
              No directories match the current search.
            </p>
          ) : (
            <Select
              label="Directory"
              options={candidateOptions}
              selected={selectedCandidateOption}
              onChange={handleCandidateChange}
              placement="bottom-start"
            />
          )}
          <p className="text-sm text-stone-500 break-all">
            {audioDirValue
              ? `Selected path: ${audioDirValue}`
              : "Select a directory to continue."}
          </p>
          {isInspecting ? (
            <p className="text-sm text-stone-500">Inspecting directory…</p>
          ) : candidateInfo ? (
            <div className="text-sm text-stone-500 space-y-1">
              <p>Audio files detected: {candidateInfo.audio_file_count}</p>
              {candidateInfo.has_nested_directories ? (
                <p className="text-amber-600">
                  This directory contains nested subfolders. Review before
                  proceeding.
                </p>
              ) : null}
              {!hasAudioFiles ? (
                <p className="text-rose-600">
                  No audio files were found. Add WAV, MP3, or FLAC files before
                  creating the dataset.
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </Group>

      <Group
        name="visibility"
        label="Visibility"
        help="Control who can access this dataset."
        error={
          errors.visibility?.message ??
          (!canCreateRestricted && visibility === "restricted"
            ? "You must be a project manager to create a restricted dataset."
            : undefined)
        }
      >
        <Select
          label="Access"
          options={VISIBILITY_OPTIONS}
          selected={selectedVisibility}
          onChange={handleVisibilityChange}
        />
      </Group>

      <div className="mb-3">
        <Submit disabled={!canSubmit}>Create Dataset</Submit>
      </div>
    </form>
  );
}
