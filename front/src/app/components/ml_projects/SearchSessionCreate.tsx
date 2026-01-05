"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import api from "@/app/api";

import {
  Group,
  Input,
  Submit,
  TextArea,
} from "@/lib/components/inputs";
import { AudioIcon, CheckIcon, ChevronDownIcon, ChevronUpIcon } from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";
import { SearchSessionCreateSchema } from "@/lib/schemas";
import type { ReferenceSound, SearchSessionCreate, Page } from "@/lib/types";

export default function SearchSessionCreate({
  mlProjectUuid,
  onCreateSession,
  onCancel,
}: {
  mlProjectUuid: string;
  onCreateSession?: (data: SearchSessionCreate) => void;
  onCancel?: () => void;
}) {
  const [showAdvanced, setShowAdvanced] = useState(false);

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
      reference_sound_ids: [],
      easy_positive_k: 5,
      boundary_n: 200,
      boundary_m: 10,
      others_p: 20,
      distance_metric: "cosine",
    },
  });

  useEffect(() => {
    register("reference_sound_ids");
  }, [register]);

  const selectedReferenceSoundIds = watch("reference_sound_ids");

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

  // Filter to only active reference sounds with embeddings
  const activeReferenceSounds = useMemo(() => {
    return referenceSounds.filter((rs) => rs.is_active && rs.embedding_count > 0);
  }, [referenceSounds]);

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
    const allIds = activeReferenceSounds.map((rs) => rs.uuid);
    setValue("reference_sound_ids", allIds, {
      shouldValidate: true,
      shouldDirty: true,
    });
  }, [activeReferenceSounds, setValue]);

  const handleDeselectAll = useCallback(() => {
    setValue("reference_sound_ids", [], {
      shouldValidate: true,
      shouldDirty: true,
    });
  }, [setValue]);

  const canSubmit =
    selectedReferenceSoundIds && selectedReferenceSoundIds.length > 0;

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
              {activeReferenceSounds.length} reference sounds available
            </span>
            <div className="flex gap-2">
              <Button
                type="button"
                mode="text"
                variant="primary"
                padding="p-1"
                onClick={handleSelectAll}
                disabled={activeReferenceSounds.length === 0}
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
            {activeReferenceSounds.length === 0 ? (
              <div className="p-4 text-center text-sm text-stone-500">
                No reference sounds available. Add reference sounds first.
              </div>
            ) : (
              activeReferenceSounds.map((rs) => {
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
                      <div className="text-xs text-stone-500 dark:text-stone-500 truncate">
                        {rs.tag.vernacular_name && (
                          <span>{rs.tag.vernacular_name}</span>
                        )}
                        {rs.tag.vernacular_name && rs.tag.canonical_name && " · "}
                        {rs.tag.canonical_name && (
                          <span className="italic">{rs.tag.canonical_name}</span>
                        )}
                      </div>
                      <div className="text-xs text-stone-400 dark:text-stone-600">
                        {rs.source === "xeno_canto" && rs.xeno_canto_id}
                        {rs.source === "clip" && "Dataset Clip"}
                        {rs.source === "upload" && "Custom Upload"}
                        {" · "}
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

      {/* Advanced Settings (Collapsible) */}
      <div className="border border-stone-200 dark:border-stone-700 rounded-md overflow-hidden">
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="w-full flex items-center justify-between px-4 py-3 bg-stone-50 dark:bg-stone-800 hover:bg-stone-100 dark:hover:bg-stone-750 transition-colors"
        >
          <span className="text-sm font-medium text-stone-700 dark:text-stone-300">
            Advanced Settings (Active Learning)
          </span>
          {showAdvanced ? (
            <ChevronUpIcon className="w-4 h-4 text-stone-500" />
          ) : (
            <ChevronDownIcon className="w-4 h-4 text-stone-500" />
          )}
        </button>

        {showAdvanced && (
          <div className="p-4 space-y-4 border-t border-stone-200 dark:border-stone-700">
            <p className="text-xs text-stone-500 dark:text-stone-400 mb-4">
              These parameters control how samples are selected for each labeling iteration.
              The defaults work well for most cases.
            </p>

            {/* Easy Positive K */}
            <Group
              name="easy_positive_k"
              label="Easy Positives (k)"
              help="Number of high-confidence positive samples per reference sound per iteration."
              error={errors.easy_positive_k?.message}
            >
              <Input
                type="number"
                min={0}
                max={50}
                {...register("easy_positive_k", { valueAsNumber: true })}
              />
            </Group>

            {/* Boundary N */}
            <Group
              name="boundary_n"
              label="Boundary Pool Size (n)"
              help="Number of boundary candidates to consider for uncertainty sampling."
              error={errors.boundary_n?.message}
            >
              <Input
                type="number"
                min={0}
                max={1000}
                {...register("boundary_n", { valueAsNumber: true })}
              />
            </Group>

            {/* Boundary M */}
            <Group
              name="boundary_m"
              label="Boundary Samples (m)"
              help="Number of boundary samples to select from the pool per iteration."
              error={errors.boundary_m?.message}
            >
              <Input
                type="number"
                min={0}
                max={100}
                {...register("boundary_m", { valueAsNumber: true })}
              />
            </Group>

            {/* Others P */}
            <Group
              name="others_p"
              label="Exploration Samples (p)"
              help="Number of random samples from the rest of the dataset per iteration."
              error={errors.others_p?.message}
            >
              <Input
                type="number"
                min={0}
                max={200}
                {...register("others_p", { valueAsNumber: true })}
              />
            </Group>

            {/* Distance Metric */}
            <Group
              name="distance_metric"
              label="Distance Metric"
              help="Method for measuring similarity between audio clips."
              error={errors.distance_metric?.message}
            >
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    value="cosine"
                    {...register("distance_metric")}
                    className="text-emerald-600"
                  />
                  <span className="text-sm">Cosine Similarity (Recommended)</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    value="euclidean"
                    {...register("distance_metric")}
                    className="text-emerald-600"
                  />
                  <span className="text-sm">Euclidean Distance</span>
                </label>
              </div>
            </Group>
          </div>
        )}
      </div>

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
