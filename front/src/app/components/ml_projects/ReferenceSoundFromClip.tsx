"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import api from "@/app/api";

import { Group, Input, Select, Submit } from "@/lib/components/inputs";
import type { Option } from "@/lib/components/inputs/Select";
import { AudioIcon, SearchIcon } from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";
import { ReferenceSoundFromClipSchema } from "@/lib/schemas";
import type { Clip, ReferenceSoundFromClip, Tag, Page } from "@/lib/types";

export default function ReferenceSoundFromClip({
  mlProjectId,
  datasetId,
  datasetUuid,
  onCreateReferenceSound,
  onCancel,
}: {
  mlProjectId: number;
  datasetId: number;
  datasetUuid?: string;
  onCreateReferenceSound?: (data: ReferenceSoundFromClip) => void;
  onCancel?: () => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
    setValue,
    watch,
  } = useForm<ReferenceSoundFromClip>({
    resolver: zodResolver(ReferenceSoundFromClipSchema),
    mode: "onChange",
    defaultValues: {
      clip_id: 0,
      tag_id: 0,
      name: "",
      start_time: 0,
      end_time: undefined,
    },
  });

  useEffect(() => {
    register("clip_id");
    register("tag_id");
    register("start_time");
    register("end_time");
  }, [register]);

  const clipId = watch("clip_id");
  const tagId = watch("tag_id");

  const [searchQuery, setSearchQuery] = useState("");
  const [selectedClip, setSelectedClip] = useState<Clip | null>(null);

  // Fetch clips from the dataset
  const {
    data: clipsData,
    isLoading: clipsLoading,
    refetch: refetchClips,
  } = useQuery<Page<Clip>>({
    queryKey: ["clips", datasetUuid, searchQuery],
    queryFn: () =>
      api.clips.getMany({
        limit: 50,
      }),
    enabled: !!datasetUuid,
    staleTime: 60_000,
  });

  const clips = clipsData?.items ?? [];

  // Fetch available tags
  const { data: tagsPage, isLoading: tagsLoading } = useQuery<Page<Tag>>({
    queryKey: ["tags", "all"],
    queryFn: () => api.tags.get({}),
    staleTime: 60_000,
  });

  const tags = tagsPage?.items ?? [];

  const clipOptions: Option<number>[] = useMemo(() => {
    const placeholder: Option<number> = {
      id: "clip-placeholder",
      label: clipsLoading ? "Loading clips..." : "Select a clip",
      value: 0,
      disabled: true,
    };
    const options = clips.map((clip, index) => ({
      id: clip.uuid,
      label: `${clip.recording?.path ?? "Unknown"} [${clip.start_time.toFixed(1)}s - ${clip.end_time.toFixed(1)}s]`,
      value: index + 1, // Use index as temporary ID
    }));
    return [placeholder, ...options];
  }, [clips, clipsLoading]);

  const selectedClipOption =
    clipOptions.find((option) => option.value === clipId) ?? clipOptions[0];

  const tagOptions: Option<number>[] = useMemo(() => {
    const placeholder: Option<number> = {
      id: "tag-placeholder",
      label: tagsLoading ? "Loading tags..." : "Select a species tag",
      value: 0,
      disabled: true,
    };
    const options = tags.map((tag, index) => ({
      id: `tag-${tag.key}-${tag.value}`,
      label: `${tag.value}${tag.key ? ` (${tag.key})` : ""}`,
      value: index + 1, // Use index as temporary ID
    }));
    return [placeholder, ...options];
  }, [tags, tagsLoading]);

  const selectedTagOption =
    tagOptions.find((option) => option.value === tagId) ?? tagOptions[0];

  const handleClipChange = useCallback(
    (value: number) => {
      setValue("clip_id", value, { shouldValidate: true, shouldDirty: true });

      // Find and set the selected clip
      const clip = value > 0 && value <= clips.length ? clips[value - 1] : null;
      setSelectedClip(clip);

      if (clip) {
        // Auto-fill time range from clip
        setValue("start_time", 0, { shouldValidate: true });
        setValue("end_time", clip.end_time - clip.start_time, { shouldValidate: true });

        // Auto-fill name if empty
        const currentName = watch("name");
        if (!currentName) {
          const recordingName = clip.recording?.path?.split("/").pop() ?? "Clip";
          setValue(
            "name",
            `${recordingName} [${clip.start_time.toFixed(1)}s]`,
            { shouldValidate: true },
          );
        }
      }
    },
    [clips, setValue, watch],
  );

  const handleTagChange = useCallback(
    (value: number) => {
      setValue("tag_id", value, { shouldValidate: true, shouldDirty: true });
    },
    [setValue],
  );

  const canSubmit = clipId > 0 && tagId > 0;

  const onSubmit = useCallback(
    (data: ReferenceSoundFromClip) => {
      if (!canSubmit) return;
      onCreateReferenceSound?.(data);
    },
    [canSubmit, onCreateReferenceSound],
  );

  return (
    <form className="flex flex-col gap-4 max-w-lg" onSubmit={handleSubmit(onSubmit)}>
      {/* Search */}
      <Group
        name="search"
        label="Search Clips"
        help="Search for clips by recording name or other criteria."
      >
        <div className="flex gap-2">
          <Input
            placeholder="Search recordings..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <Button
            type="button"
            variant="secondary"
            onClick={() => refetchClips()}
            disabled={clipsLoading}
          >
            <SearchIcon className="w-4 h-4" />
          </Button>
        </div>
      </Group>

      {/* Clip Selector */}
      <Group
        name="clip_id"
        label="Select Clip"
        help="Choose a clip from the dataset to use as a reference sound."
        error={errors.clip_id?.message}
      >
        <Select
          label="Clip"
          options={clipOptions}
          selected={selectedClipOption}
          onChange={handleClipChange}
          placement="bottom-start"
        />
      </Group>

      {/* Clip Preview */}
      {selectedClip && (
        <div className="p-4 bg-stone-50 dark:bg-stone-800 rounded-md border border-stone-200 dark:border-stone-700">
          <div className="flex items-start gap-4">
            {/* Spectrogram Thumbnail */}
            <div className="w-40 h-24 bg-stone-200 dark:bg-stone-700 rounded overflow-hidden flex-shrink-0">
              {/* Spectrogram would be loaded here */}
              <div className="flex items-center justify-center w-full h-full text-stone-400">
                <AudioIcon className="w-10 h-10" />
              </div>
            </div>
            {/* Clip Info */}
            <div className="flex-1 min-w-0">
              <h4 className="font-medium text-stone-800 dark:text-stone-200 truncate">
                {selectedClip.recording?.path?.split("/").pop() ?? "Unknown Recording"}
              </h4>
              <p className="text-sm text-stone-600 dark:text-stone-400 mt-1">
                Time: {selectedClip.start_time.toFixed(2)}s - {selectedClip.end_time.toFixed(2)}s
              </p>
              <p className="text-sm text-stone-500 dark:text-stone-500">
                Duration: {(selectedClip.end_time - selectedClip.start_time).toFixed(2)}s
              </p>
              {selectedClip.recording && (
                <p className="text-xs text-stone-400 dark:text-stone-600 mt-1">
                  Sample Rate: {selectedClip.recording.samplerate} Hz
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Tag Selector */}
      <Group
        name="tag_id"
        label="Species Tag"
        help="Select the species tag for this reference sound."
        error={errors.tag_id?.message}
      >
        <Select
          label="Species"
          options={tagOptions}
          selected={selectedTagOption}
          onChange={handleTagChange}
          placement="bottom-start"
        />
      </Group>

      {/* Name */}
      <Group
        name="name"
        label="Name"
        help="A descriptive name for this reference sound."
        error={errors.name?.message}
      >
        <Input
          placeholder="e.g., Hooded Warbler song - Site A"
          {...register("name")}
        />
      </Group>

      {/* Time Range within Clip */}
      <div className="grid grid-cols-2 gap-4">
        <Group
          name="start_time"
          label="Start Offset (s)"
          help="Start offset within the clip (relative to clip start)."
          error={errors.start_time?.message}
        >
          <Input
            type="number"
            step="0.1"
            min="0"
            placeholder="0.0"
            {...register("start_time", { valueAsNumber: true })}
          />
        </Group>
        <Group
          name="end_time"
          label="End Offset (s)"
          help="End offset within the clip."
          error={errors.end_time?.message}
        >
          <Input
            type="number"
            step="0.1"
            min="0"
            placeholder="e.g., 3.0"
            {...register("end_time", { valueAsNumber: true })}
          />
        </Group>
      </div>

      {/* Actions */}
      <div className="flex justify-end gap-3 pt-4 border-t border-stone-200 dark:border-stone-700">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Submit disabled={!canSubmit}>Create Reference Sound</Submit>
      </div>
    </form>
  );
}
