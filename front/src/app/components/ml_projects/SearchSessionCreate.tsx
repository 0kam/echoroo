"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";

import api from "@/app/api";

import {
  Group,
  Input,
  Select,
  Slider,
  Submit,
  TextArea,
} from "@/lib/components/inputs";
import type { Option } from "@/lib/components/inputs/Select";
import { AudioIcon, CheckIcon } from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";
import { SearchSessionCreateSchema } from "@/lib/schemas";
import type { ReferenceSound, SearchSessionCreate, Tag, Page } from "@/lib/types";

export default function SearchSessionCreate({
  mlProjectUuid,
  defaultThreshold = 0.7,
  onCreateSession,
  onCancel,
}: {
  mlProjectUuid: string;
  defaultThreshold?: number;
  onCreateSession?: (data: SearchSessionCreate) => void;
  onCancel?: () => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
    setValue,
    watch,
  } = useForm<SearchSessionCreate>({
    resolver: zodResolver(SearchSessionCreateSchema),
    mode: "onChange",
    defaultValues: {
      name: "",
      description: "",
      target_tag_id: 0,
      reference_sound_ids: [],
      similarity_threshold: defaultThreshold,
      max_results: 1000,
    },
  });

  useEffect(() => {
    register("target_tag_id");
    register("reference_sound_ids");
    register("similarity_threshold");
    register("max_results");
  }, [register]);

  const targetTagId = watch("target_tag_id");
  const selectedReferenceSoundIds = watch("reference_sound_ids");
  const threshold = watch("similarity_threshold") ?? defaultThreshold;
  const maxResults = watch("max_results") ?? 1000;

  // Fetch reference sounds for this ML project
  const {
    data: referenceSoundsPage,
    isLoading: referenceSoundsLoading,
  } = useQuery<Page<ReferenceSound>>({
    queryKey: ["reference-sounds", mlProjectUuid],
    queryFn: () => api.referenceSounds.getMany(mlProjectUuid, {}),
    staleTime: 30_000,
  });

  const referenceSounds = referenceSoundsPage?.items ?? [];

  // Filter to only active reference sounds
  const activeReferenceSounds = useMemo(() => {
    return referenceSounds.filter((rs) => rs.is_active && rs.has_embedding);
  }, [referenceSounds]);

  // Get unique tags from reference sounds (using tag_id as key)
  const availableTags = useMemo(() => {
    const tagMap = new Map<number, Tag>();
    activeReferenceSounds.forEach((rs) => {
      if (!tagMap.has(rs.tag_id)) {
        tagMap.set(rs.tag_id, rs.tag);
      }
    });
    return Array.from(tagMap.entries()); // Returns [tag_id, tag] pairs
  }, [activeReferenceSounds]);

  // Filter reference sounds by selected tag
  const filteredReferenceSounds = useMemo(() => {
    if (!targetTagId) return activeReferenceSounds;
    return activeReferenceSounds.filter((rs) => rs.tag_id === targetTagId);
  }, [activeReferenceSounds, targetTagId]);

  const tagOptions: Option<number>[] = useMemo(() => {
    const placeholder: Option<number> = {
      id: "tag-placeholder",
      label: referenceSoundsLoading
        ? "Loading..."
        : availableTags.length === 0
          ? "No reference sounds available"
          : "Select target species",
      value: 0,
      disabled: true,
    };
    const options = availableTags.map(([tagId, tag]) => ({
      id: `tag-${tagId}`,
      label: `${tag.value}${tag.key ? ` (${tag.key})` : ""}`,
      value: tagId,
    }));
    return [placeholder, ...options];
  }, [availableTags, referenceSoundsLoading]);

  const selectedTagOption =
    tagOptions.find((option) => option.value === targetTagId) ?? tagOptions[0];

  const handleTagChange = useCallback(
    (value: number) => {
      setValue("target_tag_id", value, { shouldValidate: true, shouldDirty: true });
      // Reset reference sound selection when tag changes
      setValue("reference_sound_ids", [], { shouldValidate: true });
    },
    [setValue],
  );

  const handleThresholdChange = useCallback(
    (value: number | number[]) => {
      const newValue = Array.isArray(value) ? value[0] : value;
      setValue("similarity_threshold", newValue, {
        shouldValidate: true,
        shouldDirty: true,
      });
    },
    [setValue],
  );

  const handleMaxResultsChange = useCallback(
    (value: number | number[]) => {
      const newValue = Array.isArray(value) ? value[0] : value;
      setValue("max_results", Math.round(newValue), {
        shouldValidate: true,
        shouldDirty: true,
      });
    },
    [setValue],
  );

  const handleToggleReferenceSound = useCallback(
    (uuid: string) => {
      const current = selectedReferenceSoundIds ?? [];
      const isSelected = current.includes(uuid);
      const newSelection = isSelected
        ? current.filter((id) => id !== uuid)
        : [...current, uuid];
      setValue("reference_sound_ids", newSelection, {
        shouldValidate: true,
        shouldDirty: true,
      });
    },
    [selectedReferenceSoundIds, setValue],
  );

  const handleSelectAll = useCallback(() => {
    const allIds = filteredReferenceSounds.map((rs) => rs.uuid);
    setValue("reference_sound_ids", allIds, {
      shouldValidate: true,
      shouldDirty: true,
    });
  }, [filteredReferenceSounds, setValue]);

  const handleDeselectAll = useCallback(() => {
    setValue("reference_sound_ids", [], {
      shouldValidate: true,
      shouldDirty: true,
    });
  }, [setValue]);

  const canSubmit =
    targetTagId > 0 && selectedReferenceSoundIds && selectedReferenceSoundIds.length > 0;

  const onSubmit = useCallback(
    (data: SearchSessionCreate) => {
      if (!canSubmit) return;
      onCreateSession?.(data);
    },
    [canSubmit, onCreateSession],
  );

  return (
    <form className="flex flex-col gap-4 max-w-2xl" onSubmit={handleSubmit(onSubmit)}>
      {/* Name */}
      <Group
        name="name"
        label="Session Name"
        help="A descriptive name for this search session."
        error={errors.name?.message}
      >
        <Input
          placeholder="e.g., Hooded Warbler Spring 2024 Search"
          {...register("name")}
        />
      </Group>

      {/* Description */}
      <Group
        name="description"
        label="Description"
        help="Optional description of the search objectives."
        error={errors.description?.message}
      >
        <TextArea
          rows={2}
          placeholder="e.g., Searching for Hooded Warbler vocalizations across all April recordings..."
          {...register("description")}
        />
      </Group>

      {/* Target Species */}
      <Group
        name="target_tag_id"
        label="Target Species"
        help="Select the species to search for."
        error={errors.target_tag_id?.message}
      >
        <Select
          label="Species"
          options={tagOptions}
          selected={selectedTagOption}
          onChange={handleTagChange}
          placement="bottom-start"
        />
      </Group>

      {/* Reference Sounds Selection */}
      <Group
        name="reference_sound_ids"
        label={`Reference Sounds (${selectedReferenceSoundIds?.length ?? 0} selected)`}
        help="Select one or more reference sounds to use for similarity matching."
        error={errors.reference_sound_ids?.message}
      >
        <div className="border border-stone-200 dark:border-stone-700 rounded-md overflow-hidden">
          {/* Selection Actions */}
          <div className="flex items-center justify-between px-3 py-2 bg-stone-50 dark:bg-stone-800 border-b border-stone-200 dark:border-stone-700">
            <span className="text-sm text-stone-600 dark:text-stone-400">
              {filteredReferenceSounds.length} reference sounds available
            </span>
            <div className="flex gap-2">
              <Button
                type="button"
                mode="text"
                variant="primary"
                padding="p-1"
                onClick={handleSelectAll}
                disabled={filteredReferenceSounds.length === 0}
              >
                Select All
              </Button>
              <Button
                type="button"
                mode="text"
                variant="secondary"
                padding="p-1"
                onClick={handleDeselectAll}
                disabled={!selectedReferenceSoundIds?.length}
              >
                Deselect All
              </Button>
            </div>
          </div>

          {/* Reference Sounds List */}
          <div className="max-h-48 overflow-y-auto">
            {filteredReferenceSounds.length === 0 ? (
              <div className="p-4 text-center text-sm text-stone-500">
                {targetTagId
                  ? "No reference sounds available for the selected species."
                  : "Select a target species to see available reference sounds."}
              </div>
            ) : (
              filteredReferenceSounds.map((rs) => {
                const isSelected = selectedReferenceSoundIds?.includes(rs.uuid) ?? false;
                return (
                  <button
                    key={rs.uuid}
                    type="button"
                    onClick={() => handleToggleReferenceSound(rs.uuid)}
                    className={`w-full flex items-center gap-3 px-3 py-2 text-left transition-colors ${
                      isSelected
                        ? "bg-emerald-50 dark:bg-emerald-900/20"
                        : "hover:bg-stone-50 dark:hover:bg-stone-800"
                    }`}
                  >
                    <div
                      className={`w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 ${
                        isSelected
                          ? "border-emerald-500 bg-emerald-500 text-white"
                          : "border-stone-300 dark:border-stone-600"
                      }`}
                    >
                      {isSelected && <CheckIcon className="w-3 h-3" />}
                    </div>
                    <div className="w-12 h-8 bg-stone-200 dark:bg-stone-700 rounded flex-shrink-0 flex items-center justify-center">
                      <AudioIcon className="w-4 h-4 text-stone-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-stone-800 dark:text-stone-200 truncate">
                        {rs.name}
                      </div>
                      <div className="text-xs text-stone-500 dark:text-stone-500">
                        {rs.source === "xeno_canto" && `XC${rs.xeno_canto_id}`}
                        {rs.source === "dataset_clip" && "Dataset Clip"}
                        {rs.source === "custom_upload" && "Custom Upload"}
                        {" - "}
                        {(rs.end_time - rs.start_time).toFixed(1)}s
                      </div>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>
      </Group>

      {/* Similarity Threshold */}
      <Group
        name="similarity_threshold"
        label={`Similarity Threshold: ${(threshold * 100).toFixed(0)}%`}
        help="Minimum similarity score for results. Higher values return fewer, more similar results."
      >
        <Slider
          label="Threshold"
          minValue={0}
          maxValue={1}
          step={0.01}
          value={threshold}
          onChange={handleThresholdChange}
          formatter={(v) => `${(v * 100).toFixed(0)}%`}
        />
      </Group>

      {/* Max Results */}
      <Group
        name="max_results"
        label={`Maximum Results: ${maxResults.toLocaleString()}`}
        help="Maximum number of results to return from the search."
      >
        <Slider
          label="Max Results"
          minValue={100}
          maxValue={10000}
          step={100}
          value={maxResults}
          onChange={handleMaxResultsChange}
          formatter={(v) => v.toLocaleString()}
        />
      </Group>

      {/* Actions */}
      <div className="flex justify-end gap-3 pt-4 border-t border-stone-200 dark:border-stone-700">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Submit disabled={!canSubmit}>Create Search Session</Submit>
      </div>
    </form>
  );
}
