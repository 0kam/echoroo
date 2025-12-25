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
import Loading from "@/lib/components/ui/Loading";
import { ReferenceSoundFromXenoCantoSchema } from "@/lib/schemas";
import type { ReferenceSoundFromXenoCanto, Tag, Page } from "@/lib/types";

interface XenoCantoPreview {
  id: string;
  species: string;
  common_name: string;
  duration: number;
  url: string;
  audio_url: string;
  spectrogram_url?: string;
}

export default function ReferenceSoundFromXenoCanto({
  mlProjectId,
  onImport,
  onCancel,
}: {
  mlProjectId: number;
  onImport?: (data: ReferenceSoundFromXenoCanto) => void;
  onCancel?: () => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
    setValue,
    watch,
  } = useForm<ReferenceSoundFromXenoCanto>({
    resolver: zodResolver(ReferenceSoundFromXenoCantoSchema),
    mode: "onChange",
    defaultValues: {
      xeno_canto_id: "",
      tag_id: 0,
      name: "",
      start_time: 0,
      end_time: undefined,
    },
  });

  useEffect(() => {
    register("tag_id");
    register("start_time");
    register("end_time");
  }, [register]);

  const xcId = watch("xeno_canto_id");
  const tagId = watch("tag_id");
  const startTime = watch("start_time") ?? 0;
  const endTime = watch("end_time");

  const [preview, setPreview] = useState<XenoCantoPreview | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [audioElement, setAudioElement] = useState<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  // Fetch available tags
  const { data: tagsPage, isLoading: tagsLoading } = useQuery<Page<Tag>>({
    queryKey: ["tags", "all"],
    queryFn: () => api.tags.get({}),
    staleTime: 60_000,
  });

  const tags = tagsPage?.items ?? [];

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

  const handleTagChange = useCallback(
    (value: number) => {
      setValue("tag_id", value, { shouldValidate: true, shouldDirty: true });
    },
    [setValue],
  );

  const handleLoadPreview = useCallback(async () => {
    if (!xcId) return;

    setIsLoadingPreview(true);
    setPreviewError(null);
    setPreview(null);

    try {
      // For now, show a placeholder - XC API would need to be implemented
      setPreviewError("Xeno-Canto preview requires backend integration. Enter XC ID and tag to import.");
    } catch (error) {
      setPreviewError(
        error instanceof Error
          ? error.message
          : "Failed to load Xeno-Canto recording",
      );
    } finally {
      setIsLoadingPreview(false);
    }
  }, [xcId]);

  const handlePlayPreview = useCallback(() => {
    if (!preview?.audio_url) return;

    if (audioElement) {
      audioElement.pause();
      audioElement.currentTime = 0;
    }

    const audio = new Audio(preview.audio_url);
    audio.currentTime = startTime;

    audio.addEventListener("timeupdate", () => {
      if (endTime && audio.currentTime >= endTime) {
        audio.pause();
        setIsPlaying(false);
      }
    });

    audio.addEventListener("ended", () => {
      setIsPlaying(false);
    });

    audio.play();
    setAudioElement(audio);
    setIsPlaying(true);
  }, [preview, startTime, endTime, audioElement]);

  const handleStopPreview = useCallback(() => {
    if (audioElement) {
      audioElement.pause();
      audioElement.currentTime = 0;
      setIsPlaying(false);
    }
  }, [audioElement]);

  // Cleanup audio on unmount
  useEffect(() => {
    return () => {
      if (audioElement) {
        audioElement.pause();
      }
    };
  }, [audioElement]);

  const canSubmit = !!xcId && tagId > 0;

  const onSubmit = useCallback(
    (data: ReferenceSoundFromXenoCanto) => {
      if (!canSubmit) return;
      onImport?.(data);
    },
    [canSubmit, onImport],
  );

  return (
    <form className="flex flex-col gap-4 max-w-lg" onSubmit={handleSubmit(onSubmit)}>
      {/* XC ID Input */}
      <Group
        name="xeno_canto_id"
        label="Xeno-Canto ID"
        help="Enter the numeric ID from the Xeno-Canto recording URL (e.g., 12345 from xeno-canto.org/12345)."
        error={errors.xeno_canto_id?.message}
      >
        <div className="flex gap-2">
          <Input
            placeholder="e.g., 12345"
            {...register("xeno_canto_id")}
          />
          <Button
            type="button"
            variant="secondary"
            onClick={handleLoadPreview}
            disabled={!xcId || isLoadingPreview}
          >
            {isLoadingPreview ? (
              <Loading />
            ) : (
              <>
                <SearchIcon className="w-4 h-4 mr-1" />
                Load
              </>
            )}
          </Button>
        </div>
      </Group>

      {/* Preview Error */}
      {previewError && (
        <div className="p-3 bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800 rounded-md text-sm text-rose-700 dark:text-rose-300">
          {previewError}
        </div>
      )}

      {/* Preview */}
      {preview && (
        <div className="p-4 bg-stone-50 dark:bg-stone-800 rounded-md border border-stone-200 dark:border-stone-700">
          <div className="flex items-start gap-4">
            {/* Spectrogram */}
            <div className="w-32 h-20 bg-stone-200 dark:bg-stone-700 rounded overflow-hidden flex-shrink-0">
              {preview.spectrogram_url ? (
                <img
                  src={preview.spectrogram_url}
                  alt="Spectrogram preview"
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="flex items-center justify-center w-full h-full text-stone-400">
                  <AudioIcon className="w-8 h-8" />
                </div>
              )}
            </div>
            {/* Info */}
            <div className="flex-1 min-w-0">
              <h4 className="font-medium text-stone-800 dark:text-stone-200">
                {preview.common_name}
              </h4>
              <p className="text-sm text-stone-600 dark:text-stone-400 italic">
                {preview.species}
              </p>
              <p className="text-xs text-stone-500 dark:text-stone-500 mt-1">
                Duration: {preview.duration.toFixed(1)}s
              </p>
              <a
                href={preview.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
              >
                View on Xeno-Canto
              </a>
            </div>
          </div>
          {/* Audio Preview Player */}
          <div className="mt-3 flex items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              padding="p-2"
              onClick={isPlaying ? handleStopPreview : handlePlayPreview}
            >
              {isPlaying ? "Stop" : "Play Preview"}
            </Button>
            {isPlaying && (
              <span className="text-xs text-stone-500">
                Playing {startTime.toFixed(1)}s - {endTime?.toFixed(1) ?? preview.duration.toFixed(1)}s
              </span>
            )}
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
          placeholder="e.g., Hooded Warbler song (XC12345)"
          {...register("name")}
        />
      </Group>

      {/* Time Range */}
      <div className="grid grid-cols-2 gap-4">
        <Group
          name="start_time"
          label="Start Time (s)"
          help="Start time in seconds."
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
          label="End Time (s)"
          help="End time in seconds."
          error={errors.end_time?.message}
        >
          <Input
            type="number"
            step="0.1"
            min="0"
            placeholder="e.g., 5.0"
            {...register("end_time", { valueAsNumber: true })}
          />
        </Group>
      </div>

      {/* Actions */}
      <div className="flex justify-end gap-3 pt-4 border-t border-stone-200 dark:border-stone-700">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Submit disabled={!canSubmit}>Import from Xeno-Canto</Submit>
      </div>
    </form>
  );
}
