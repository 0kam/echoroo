import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import api from "@/app/api";
import useActiveUser from "@/app/hooks/api/useActiveUser";
import useMyGroups from "@/app/hooks/api/useMyGroups";

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
} from "@/lib/types";

/**
 * Component for creating a new dataset.
 */
export default function CreateDataset({
  onCreateDataset,
}: {
  onCreateDataset?: (dataset: DatasetCreate) => void;
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
      visibility: "private",
      owner_group_id: null,
    },
  });

  useEffect(() => {
    register("visibility");
    register("owner_group_id");
    register("audio_dir");
  }, [register]);

  const audioDirValue = watch("audio_dir");

  const {
    data: candidates = [],
    isLoading: candidatesLoading,
    refetch: refetchCandidates,
    error: candidatesError,
  } = useQuery({
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

  const placeholderOption = useMemo<Option<string>>(
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
      placeholderOption,
      ...filteredCandidates.map((candidate) => ({
        id: candidate.relative_path,
        label: candidate.relative_path,
        value: candidate.relative_path,
      })),
    ],
    [filteredCandidates, placeholderOption],
  );

  const selectedCandidateOption: Option<string> = selectedCandidate
    ? {
        id: selectedCandidate.relative_path,
        label: selectedCandidate.relative_path,
        value: selectedCandidate.relative_path,
      }
    : placeholderOption;

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
  const { data: myGroups, isLoading: groupsLoading } = useMyGroups();

  const managerGroups = useMemo(() => {
    if (!myGroups?.length || !activeUser) return [];
    return myGroups.filter((group) =>
      group.memberships.some(
        (membership) =>
          membership.user_id === activeUser.id &&
          membership.role === "manager",
      ),
    );
  }, [myGroups, activeUser]);

  const groupOptions: Option<number | null>[] = useMemo(() => {
    const opts = managerGroups.map((group) => ({
      id: group.id,
      label: group.name,
      value: group.id,
    }));
    return [
      {
        id: "none",
        label:
          opts.length === 0
            ? "No manager groups available"
            : "Select a group",
        value: null,
        disabled: opts.length === 0,
      },
      ...opts,
    ];
  }, [managerGroups]);

  const visibilityOptions: Option<VisibilityLevel>[] = useMemo(
    () => [
      {
        id: "public",
        label: "🌍 Public – All authenticated users can view and use",
        value: "public",
      },
      {
        id: "restricted",
        label: "👥 Restricted – Only selected group members",
        value: "restricted",
      },
      {
        id: "private",
        label: "🔒 Private – Only you",
        value: "private",
      },
    ],
    [],
  );

  const visibility = watch("visibility");
  const ownerGroupId = watch("owner_group_id");

  const selectedVisibility = useMemo<Option<VisibilityLevel>>(() => {
    return (
      visibilityOptions.find((option) => option.value === visibility) ??
      visibilityOptions[2]
    );
  }, [visibility, visibilityOptions]);

  const selectedGroup = useMemo<Option<number | null>>(() => {
    return (
      groupOptions.find((option) => option.value === ownerGroupId) ??
      groupOptions[0]
    );
  }, [groupOptions, ownerGroupId]);

  const handleVisibilityChange = useCallback(
    (value: VisibilityLevel) => {
      setValue("visibility", value, { shouldValidate: true });
      if (value !== "restricted") {
        setValue("owner_group_id", null, { shouldValidate: true });
      }
    },
    [setValue],
  );

  const handleGroupChange = useCallback(
    (value: number | null) => {
      setValue("owner_group_id", value, {
        shouldValidate: true,
        shouldDirty: true,
      });
    },
    [setValue],
  );

  const isRestricted = visibility === "restricted";
  const canCreateRestricted = !isRestricted || managerGroups.length > 0;
  const canSubmit =
    canCreateRestricted &&
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
      <Group
        name="name"
        label="Name"
        help="Please provide a name for the dataset."
        error={errors.name?.message}
      >
        <Input {...register("name")} />
      </Group>
      <Group
        name="description"
        label="Description"
        help="Describe the dataset."
        error={errors.description?.message}
      >
        <TextArea {...register("description")} />
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
              No subdirectories were found. Add data with the external uploader
              and refresh this list.
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
                  This directory contains nested subfolders. Please review and
                  tidy up if needed.
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
        help="Control who can access this dataset"
        error={errors.visibility?.message}
      >
        <Select
          label="Access"
          options={visibilityOptions}
          selected={selectedVisibility}
          onChange={handleVisibilityChange}
        />
      </Group>
      {isRestricted ? (
        <Group
          name="owner_group_id"
          label="Group"
          help="Choose which group can access this dataset"
          error={errors.owner_group_id?.message}
        >
          {groupsLoading ? (
            <p className="text-sm text-stone-500">Loading groups…</p>
          ) : (
            <Select
              label="Group"
              options={groupOptions}
              selected={selectedGroup}
              onChange={handleGroupChange}
            />
          )}
          {managerGroups.length === 0 ? (
            <p className="mt-2 text-xs text-amber-600">
              You must be a manager of a group to create restricted datasets.
            </p>
          ) : null}
        </Group>
      ) : null}
      <div className="mb-3">
        <Submit disabled={!canSubmit}>Create Dataset</Submit>
      </div>
    </form>
  );
}
