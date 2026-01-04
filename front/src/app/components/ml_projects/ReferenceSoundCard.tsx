"use client";

import classNames from "classnames";

import {
  AudioIcon,
  CloseIcon,
  DeleteIcon,
  PlayIcon,
  TagIcon,
  TimeIcon,
  WarningIcon,
} from "@/lib/components/icons";
import { Toggle } from "@/lib/components/inputs";
import Alert from "@/lib/components/ui/Alert";
import Button from "@/lib/components/ui/Button";

import type { ReferenceSound, ReferenceSoundSource } from "@/lib/types";

/**
 * Badge configuration for reference sound sources.
 */
const SOURCE_CONFIG: Record<
  ReferenceSoundSource,
  { label: string; className: string }
> = {
  xeno_canto: {
    label: "XC",
    className: "bg-orange-100 text-orange-700 border-orange-300",
  },
  dataset_clip: {
    label: "Clip",
    className: "bg-blue-100 text-blue-700 border-blue-300",
  },
  custom_upload: {
    label: "Upload",
    className: "bg-purple-100 text-purple-700 border-purple-300",
  },
};

function SourceBadge({ source }: { source: ReferenceSoundSource }) {
  const config = SOURCE_CONFIG[source];
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 text-xs font-medium rounded border ${config.className}`}
    >
      {config.label}
    </span>
  );
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(1);
  return mins > 0 ? `${mins}:${secs.padStart(4, "0")}` : `${secs}s`;
}

export default function ReferenceSoundCard({
  referenceSound,
  spectrogramUrl,
  isPlaying = false,
  onPlay,
  onStop,
  onToggleActive,
  onDelete,
}: {
  referenceSound: ReferenceSound;
  spectrogramUrl?: string;
  isPlaying?: boolean;
  onPlay?: () => void;
  onStop?: () => void;
  onToggleActive?: (isActive: boolean) => void;
  onDelete?: () => void;
}) {
  const duration = referenceSound.end_time - referenceSound.start_time;

  return (
    <div
      className={classNames(
        "flex flex-col gap-2 p-3 rounded-lg border transition-colors",
        referenceSound.is_active
          ? "border-stone-300 dark:border-stone-600 bg-white dark:bg-stone-800"
          : "border-stone-200 dark:border-stone-700 bg-stone-50 dark:bg-stone-900 opacity-60",
      )}
    >
      {/* Spectrogram Thumbnail */}
      <div className="relative w-full h-20 bg-stone-200 dark:bg-stone-700 rounded overflow-hidden">
        {spectrogramUrl ? (
          <img
            src={spectrogramUrl}
            alt={`Spectrogram for ${referenceSound.name}`}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="flex items-center justify-center w-full h-full text-stone-400">
            <AudioIcon className="w-8 h-8" />
          </div>
        )}
        {/* Play button overlay */}
        <button
          type="button"
          onClick={isPlaying ? onStop : onPlay}
          className="absolute inset-0 flex items-center justify-center bg-black/20 hover:bg-black/30 transition-colors"
        >
          {isPlaying ? (
            <div className="w-10 h-10 rounded-full bg-white/90 flex items-center justify-center">
              <CloseIcon className="w-5 h-5 text-stone-700" />
            </div>
          ) : (
            <div className="w-10 h-10 rounded-full bg-white/90 flex items-center justify-center">
              <PlayIcon className="w-5 h-5 text-stone-700" />
            </div>
          )}
        </button>
      </div>

      {/* Name and Source */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-medium text-stone-800 dark:text-stone-200 truncate">
            {referenceSound.name}
          </h4>
        </div>
        <SourceBadge source={referenceSound.source} />
      </div>

      {/* Species Tag */}
      <div className="flex items-center gap-1 text-xs text-stone-600 dark:text-stone-400">
        <TagIcon className="w-3.5 h-3.5" />
        <span className="truncate">{referenceSound.tag.value}</span>
      </div>

      {/* Time Range */}
      <div className="flex items-center gap-1 text-xs text-stone-500 dark:text-stone-500">
        <TimeIcon className="w-3.5 h-3.5" />
        <span>
          {formatTime(referenceSound.start_time)} - {formatTime(referenceSound.end_time)}
          <span className="text-stone-400 ml-1">({formatTime(duration)})</span>
        </span>
      </div>

      {/* Embedding Status */}
      {referenceSound.has_embedding ? (
        <div className="text-xs text-emerald-600 dark:text-emerald-400">
          Embedding ready
        </div>
      ) : (
        <div className="text-xs text-amber-600 dark:text-amber-400">
          Embedding pending
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between pt-2 border-t border-stone-200 dark:border-stone-700">
        <div className="flex items-center gap-2">
          <Toggle
            isSelected={referenceSound.is_active}
            onChange={onToggleActive}
            label="Active"
          />
          <span className="text-xs text-stone-500">
            {referenceSound.is_active ? "Active" : "Inactive"}
          </span>
        </div>
        <Alert
          title={
            <>
              <WarningIcon className="inline-block mr-2 w-6 h-6 text-red-500" />
              Delete reference sound?
            </>
          }
          button={
            <>
              <DeleteIcon className="inline-block mr-1 w-4 h-4" />
              Delete
            </>
          }
          mode="text"
          variant="danger"
          padding="px-2 py-1"
        >
          {({ close }) => (
            <>
              <div className="flex flex-col gap-2">
                <p>
                  Are you sure you want to delete this reference sound? This
                  action cannot be undone.
                </p>
                <h2 className="p-3 font-semibold text-center text-stone-800 dark:text-stone-200">
                  {referenceSound.name}
                </h2>
              </div>
              <div className="flex flex-row gap-2 justify-end mt-4">
                <Button
                  tabIndex={0}
                  mode="text"
                  variant="danger"
                  onClick={() => {
                    onDelete?.();
                    close();
                  }}
                >
                  <DeleteIcon className="inline-block mr-2 w-5 h-5" />
                  Delete
                </Button>
                <Button
                  tabIndex={1}
                  mode="outline"
                  variant="primary"
                  onClick={close}
                >
                  <CloseIcon className="inline-block mr-2 w-5 h-5" />
                  Cancel
                </Button>
              </div>
            </>
          )}
        </Alert>
      </div>
    </div>
  );
}
