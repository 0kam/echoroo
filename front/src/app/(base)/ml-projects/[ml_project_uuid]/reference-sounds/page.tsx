"use client";

/**
 * Reference Sounds management page.
 *
 * Displays a list of reference sounds with spectrogram thumbnails.
 * Allows adding reference sounds from Xeno-Canto or dataset clips,
 * toggling active/inactive state, and deleting sounds.
 *
 * Uses spectrogram-based segment selection for precise time range selection.
 */
import { useCallback, useContext, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  Music,
  Globe,
  Database,
  ToggleLeft,
  ToggleRight,
  Trash2,
  ExternalLink,
  CheckCircle,
  XCircle,
  Loader2,
  X,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Play,
} from "lucide-react";

import api from "@/app/api";
import TagSearchBar from "@/app/components/tags/TagSearchBar";
import SpectrogramSegmentSelector from "@/app/components/ml_projects/SpectrogramSegmentSelector";
import { DEFAULT_SPECTROGRAM_PARAMETERS } from "@/lib/constants";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import { DialogOverlay } from "@/lib/components/ui/Dialog";
import Alert from "@/lib/components/ui/Alert";
import TagComponent from "@/lib/components/tags/Tag";

import type { ReferenceSound, Tag } from "@/lib/types";

import MLProjectContext from "../context";

function ReferenceSoundCard({
  sound,
  mlProjectUuid,
  onToggle,
  onDelete,
}: {
  sound: ReferenceSound;
  mlProjectUuid: string;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const [spectrogramError, setSpectrogramError] = useState(false);

  const sourceIcon = {
    xeno_canto: <Globe className="w-4 h-4" />,
    upload: <Music className="w-4 h-4" />,
    clip: <Database className="w-4 h-4" />,
  };

  const sourceLabel = {
    xeno_canto: "Xeno-Canto",
    upload: "Custom Upload",
    clip: "Dataset Clip",
  };

  // Get audio URL based on source
  const getAudioUrl = () => {
    if (sound.source === "xeno_canto" && sound.xeno_canto_id) {
      // Include time range parameters for Xeno-Canto audio
      const params = new URLSearchParams({
        start_time: sound.start_time.toString(),
        end_time: sound.end_time.toString(),
      });
      return `/api/v1/ml_projects/${mlProjectUuid}/reference_sounds/xeno_canto/${sound.xeno_canto_id}/audio?${params}`;
    } else if (sound.source === "clip" && sound.clip) {
      return api.audio.getStreamUrl({
        recording: sound.clip.recording,
        startTime: sound.start_time,
        endTime: sound.end_time,
      });
    }
    return null;
  };

  // Get spectrogram URL based on source
  const getSpectrogramUrl = () => {
    if (sound.source === "xeno_canto" && sound.xeno_canto_id) {
      // Include time range and spectrogram parameters for consistency with search session page
      const params = new URLSearchParams({
        start_time: sound.start_time.toString(),
        end_time: sound.end_time.toString(),
        cmap: DEFAULT_SPECTROGRAM_PARAMETERS.cmap || "twilight",
      });
      return `/api/v1/ml_projects/${mlProjectUuid}/reference_sounds/xeno_canto/${sound.xeno_canto_id}/spectrogram?${params}`;
    } else if (sound.source === "clip" && sound.clip) {
      return api.spectrograms.getUrl({
        uuid: sound.clip.recording.uuid,
        interval: { min: sound.start_time, max: sound.end_time },
        ...DEFAULT_SPECTROGRAM_PARAMETERS,
      });
    }
    return null;
  };

  const handlePlayAudio = (e: React.MouseEvent) => {
    e.stopPropagation();
    const audioUrl = getAudioUrl();
    if (audioUrl) {
      const audio = new Audio(audioUrl);
      audio.play().catch((error) => {
        console.error("Failed to play audio:", error);
      });
    }
  };

  const spectrogramUrl = getSpectrogramUrl();
  const showSpectrogram = spectrogramUrl && !spectrogramError;

  return (
    <Card className="relative">
      {/* Spectrogram thumbnail with play button */}
      <div className="aspect-[3/1] bg-stone-100 dark:bg-stone-800 rounded-lg mb-3 flex items-center justify-center relative overflow-hidden group">
        {showSpectrogram ? (
          <>
            <img
              src={spectrogramUrl}
              alt="Spectrogram"
              className="absolute inset-0 w-full h-full object-cover"
              onError={() => setSpectrogramError(true)}
            />
            {/* Play button overlay - visible on hover */}
            <button
              onClick={handlePlayAudio}
              className="absolute inset-0 flex items-center justify-center bg-black/0 hover:bg-black/30 transition-colors"
            >
              <Play className="w-8 h-8 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
            {/* Time badge */}
            <span className="absolute bottom-2 left-2 px-2 py-0.5 text-xs bg-black/50 text-white rounded">
              {sound.start_time.toFixed(2)}s - {sound.end_time.toFixed(2)}s
            </span>
          </>
        ) : (
          <>
            {/* Placeholder for when spectrogram is not available */}
            <div className="text-stone-400 flex flex-col items-center gap-2">
              <Music className="w-8 h-8" />
              <span className="text-xs">
                {sound.start_time.toFixed(2)}s - {sound.end_time.toFixed(2)}s
              </span>
            </div>
            {/* Play button for placeholder */}
            {getAudioUrl() && (
              <button
                onClick={handlePlayAudio}
                className="absolute top-2 right-2 p-2 bg-black/50 hover:bg-black/70 rounded-full transition-colors"
              >
                <Play className="w-4 h-4 text-white" />
              </button>
            )}
          </>
        )}
      </div>

      {/* Sound info */}
      <div className="space-y-2">
        <div className="flex items-start justify-between">
          <h4 className="font-medium text-stone-900 dark:text-stone-100 line-clamp-1">
            {sound.name}
          </h4>
          <div className="flex items-center gap-1">
            {sound.is_active ? (
              <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                <CheckCircle className="w-3 h-3" />
                Active
              </span>
            ) : (
              <span className="flex items-center gap-1 text-xs text-stone-400">
                <XCircle className="w-3 h-3" />
                Inactive
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 text-sm text-stone-500 dark:text-stone-400">
          {sourceIcon[sound.source]}
          <span>{sourceLabel[sound.source]}</span>
          {sound.xeno_canto_id && (
            <a
              href={
                sound.xeno_canto_url ||
                `https://xeno-canto.org/${sound.xeno_canto_id}`
              }
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-500 hover:text-blue-600 inline-flex items-center gap-1"
            >
              XC{sound.xeno_canto_id}
              <ExternalLink className="w-3 h-3" />
            </a>
          )}
        </div>

        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 text-xs bg-stone-100 dark:bg-stone-700 rounded-full">
            {sound.tag.canonical_name || `${sound.tag.key}: ${sound.tag.value}`}
            {sound.tag.vernacular_name && ` (${sound.tag.vernacular_name})`}
          </span>
          {sound.has_embedding ? (
            <span className="px-2 py-0.5 text-xs bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 rounded-full">
              Embedding ready
            </span>
          ) : (
            <span className="px-2 py-0.5 text-xs bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 rounded-full">
              No embedding
            </span>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 mt-4 pt-3 border-t border-stone-200 dark:border-stone-700">
        <Button
          variant="secondary"
          mode="text"
          className="flex-1"
          onClick={onToggle}
        >
          {sound.is_active ? (
            <>
              <ToggleRight className="w-4 h-4 mr-1 text-emerald-500" />
              Deactivate
            </>
          ) : (
            <>
              <ToggleLeft className="w-4 h-4 mr-1" />
              Activate
            </>
          )}
        </Button>
        <Alert
          title={
            <>
              <AlertTriangle className="inline-block mr-2 w-6 h-6 text-red-500" />
              Delete reference sound?
            </>
          }
          button={<Trash2 className="w-4 h-4" />}
          mode="text"
          variant="danger"
          padding="p-2"
        >
          {({ close }) => (
            <>
              <div className="flex flex-col gap-2">
                <p>
                  Are you sure you want to delete this reference sound? This
                  action cannot be undone.
                </p>
                <h2 className="p-3 font-semibold text-center text-stone-800 dark:text-stone-200">
                  {sound.name}
                </h2>
              </div>
              <div className="flex flex-row gap-2 justify-end mt-4">
                <Button
                  mode="text"
                  variant="danger"
                  onClick={() => {
                    onDelete();
                    close();
                  }}
                >
                  <Trash2 className="inline-block mr-2 w-5 h-5" />
                  Delete
                </Button>
                <Button mode="outline" variant="primary" onClick={close}>
                  <X className="inline-block mr-2 w-5 h-5" />
                  Cancel
                </Button>
              </div>
            </>
          )}
        </Alert>
      </div>
    </Card>
  );
}

// Dialog step types
type XenoCantoDialogStep = "info" | "select";
type ClipDialogStep = "info" | "select";

function AddFromXenoCantoDialog({
  isOpen,
  onClose,
  mlProjectUuid,
  onSuccess,
}: {
  isOpen: boolean;
  onClose: () => void;
  mlProjectUuid: string;
  onSuccess: () => void;
}) {
  // Step state
  const [step, setStep] = useState<XenoCantoDialogStep>("info");

  // Form state
  const [xenoCantoId, setXenoCantoId] = useState("");
  const [name, setName] = useState("");
  const [selectedTag, setSelectedTag] = useState<Tag | null>(null);

  // Segment selection state
  const [startTime, setStartTime] = useState<number>(0);
  const [endTime, setEndTime] = useState<number>(5);
  const [audioError, setAudioError] = useState<string | null>(null);

  // Submission state
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Audio URL for Xeno-Canto
  // Note: This assumes a backend endpoint that proxies Xeno-Canto audio
  const audioUrl =
    step === "select" && xenoCantoId
      ? `/api/v1/ml_projects/${mlProjectUuid}/reference_sounds/xeno_canto/${xenoCantoId}/audio`
      : "";

  const handleTagSelect = useCallback((tag: Tag) => {
    setSelectedTag(tag);
  }, []);

  const handleClearTag = useCallback(() => {
    setSelectedTag(null);
  }, []);

  const handleLoadAudio = useCallback(() => {
    if (!xenoCantoId || !name || !selectedTag?.id) return;
    setAudioError(null);
    setStep("select");
  }, [xenoCantoId, name, selectedTag]);

  const handleSegmentChange = useCallback(
    (start: number, end: number) => {
      setStartTime(start);
      setEndTime(end);
    },
    [],
  );

  const handleBack = useCallback(() => {
    setStep("info");
  }, []);

  const handleSubmit = async () => {
    if (!xenoCantoId || !name || !selectedTag?.id) return;

    setIsSubmitting(true);
    try {
      await api.referenceSounds.createFromXenoCanto(mlProjectUuid, {
        xeno_canto_id: xenoCantoId,
        name,
        tag_id: selectedTag.id,
        start_time: startTime,
        end_time: endTime,
      });
      toast.success("Reference sound added from Xeno-Canto");
      // Reset state
      setXenoCantoId("");
      setName("");
      setSelectedTag(null);
      setStartTime(0);
      setEndTime(5);
      setStep("info");
      onSuccess();
      onClose();
    } catch (error) {
      toast.error("Failed to add reference sound");
      console.error(error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = useCallback(() => {
    // Reset state when closing
    setStep("info");
    setXenoCantoId("");
    setName("");
    setSelectedTag(null);
    setStartTime(0);
    setEndTime(5);
    setAudioError(null);
    onClose();
  }, [onClose]);

  const canProceedToSelect = xenoCantoId && name && selectedTag?.id;
  const canSubmit = startTime < endTime && endTime - startTime >= 1;

  return (
    <DialogOverlay
      title={
        step === "info"
          ? "Add from Xeno-Canto"
          : "Select Segment"
      }
      isOpen={isOpen}
      onClose={handleClose}
    >
      <div className={step === "select" ? "w-[600px]" : "w-[400px]"}>
        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-4">
          <div
            className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-medium ${
              step === "info"
                ? "bg-emerald-500 text-white"
                : "bg-stone-200 dark:bg-stone-700 text-stone-600 dark:text-stone-400"
            }`}
          >
            1
          </div>
          <div className="flex-1 h-0.5 bg-stone-200 dark:bg-stone-700" />
          <div
            className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-medium ${
              step === "select"
                ? "bg-emerald-500 text-white"
                : "bg-stone-200 dark:bg-stone-700 text-stone-600 dark:text-stone-400"
            }`}
          >
            2
          </div>
        </div>

        {step === "info" ? (
          /* Step 1: Basic info */
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
                Xeno-Canto Recording ID
              </label>
              <input
                type="text"
                value={xenoCantoId}
                onChange={(e) => setXenoCantoId(e.target.value)}
                className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
                placeholder="e.g., 123456"
              />
              <p className="text-xs text-stone-500 mt-1">
                Enter the numeric ID from xeno-canto.org
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
                Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
                placeholder="Reference sound name"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
                Species Tag
              </label>
              {selectedTag ? (
                <div className="flex items-center gap-2 p-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-stone-50 dark:bg-stone-800">
                  <TagComponent
                    tag={selectedTag}
                    color="emerald"
                    level={3}
                    disabled
                    className="pointer-events-none"
                  />
                  <button
                    type="button"
                    onClick={handleClearTag}
                    className="ml-auto p-1 text-stone-400 hover:text-stone-600 dark:hover:text-stone-300 rounded"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ) : (
                <TagSearchBar
                  onSelectTag={handleTagSelect}
                  onCreateTag={handleTagSelect}
                />
              )}
            </div>

            <div className="flex justify-end gap-2 pt-4">
              <Button type="button" variant="secondary" onClick={handleClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={!canProceedToSelect}
                onClick={handleLoadAudio}
              >
                Load Audio
                <ChevronRight className="w-4 h-4 ml-1" />
              </Button>
            </div>
          </div>
        ) : (
          /* Step 2: Segment selection */
          <div className="space-y-4">
            {audioError ? (
              <div className="p-4 bg-red-50 dark:bg-red-900/20 rounded-lg text-red-600 dark:text-red-400">
                <p className="font-medium">Failed to load audio</p>
                <p className="text-sm mt-1">{audioError}</p>
                <Button
                  variant="secondary"
                  className="mt-3"
                  onClick={handleBack}
                >
                  <ChevronLeft className="w-4 h-4 mr-1" />
                  Back
                </Button>
              </div>
            ) : (
              <>
                <div className="p-3 bg-stone-50 dark:bg-stone-800 rounded-lg">
                  <div className="flex items-center gap-4 text-sm">
                    <div>
                      <span className="text-stone-500 dark:text-stone-400">
                        ID:
                      </span>{" "}
                      <span className="font-medium">{xenoCantoId}</span>
                    </div>
                    <div>
                      <span className="text-stone-500 dark:text-stone-400">
                        Name:
                      </span>{" "}
                      <span className="font-medium">{name}</span>
                    </div>
                    {selectedTag && (
                      <TagComponent
                        tag={selectedTag}
                        color="emerald"
                        level={3}
                        disabled
                        className="pointer-events-none"
                      />
                    )}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-2">
                    Select Audio Segment
                  </label>
                  <SpectrogramSegmentSelector
                    audioUrl={audioUrl}
                    onSegmentChange={handleSegmentChange}
                    initialStartTime={startTime}
                    initialEndTime={endTime}
                    height={180}
                  />
                </div>

                <div className="flex justify-between gap-2 pt-4">
                  <Button variant="secondary" onClick={handleBack}>
                    <ChevronLeft className="w-4 h-4 mr-1" />
                    Back
                  </Button>
                  <Button
                    variant="primary"
                    disabled={!canSubmit || isSubmitting}
                    onClick={handleSubmit}
                  >
                    {isSubmitting ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Adding...
                      </>
                    ) : (
                      "Add Reference Sound"
                    )}
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </DialogOverlay>
  );
}

function AddFromClipDialog({
  isOpen,
  onClose,
  mlProjectUuid,
  onSuccess,
}: {
  isOpen: boolean;
  onClose: () => void;
  mlProjectUuid: string;
  onSuccess: () => void;
}) {
  // Step state
  const [step, setStep] = useState<ClipDialogStep>("info");

  // Form state
  const [clipUuid, setClipUuid] = useState("");
  const [name, setName] = useState("");
  const [selectedTag, setSelectedTag] = useState<Tag | null>(null);

  // Segment selection state
  const [startTime, setStartTime] = useState<number>(0);
  const [endTime, setEndTime] = useState<number>(5);
  const [audioError, setAudioError] = useState<string | null>(null);

  // Submission state
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Audio URL for clip
  const audioUrl =
    step === "select" && clipUuid
      ? `/api/v1/clips/${clipUuid}/audio`
      : "";

  const handleTagSelect = useCallback((tag: Tag) => {
    setSelectedTag(tag);
  }, []);

  const handleClearTag = useCallback(() => {
    setSelectedTag(null);
  }, []);

  const handleLoadAudio = useCallback(() => {
    if (!clipUuid || !name || !selectedTag?.id) return;
    setAudioError(null);
    setStep("select");
  }, [clipUuid, name, selectedTag]);

  const handleSegmentChange = useCallback(
    (start: number, end: number) => {
      setStartTime(start);
      setEndTime(end);
    },
    [],
  );

  const handleBack = useCallback(() => {
    setStep("info");
  }, []);

  const handleSubmit = async () => {
    if (!clipUuid || !name || !selectedTag?.id) return;

    setIsSubmitting(true);
    try {
      await api.referenceSounds.createFromClip(mlProjectUuid, {
        clip_uuid: clipUuid,
        name,
        tag_id: selectedTag.id,
        start_time: startTime,
        end_time: endTime,
      });
      toast.success("Reference sound added from clip");
      // Reset state
      setClipUuid("");
      setName("");
      setSelectedTag(null);
      setStartTime(0);
      setEndTime(5);
      setStep("info");
      onSuccess();
      onClose();
    } catch (error) {
      toast.error("Failed to add reference sound");
      console.error(error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = useCallback(() => {
    // Reset state when closing
    setStep("info");
    setClipUuid("");
    setName("");
    setSelectedTag(null);
    setStartTime(0);
    setEndTime(5);
    setAudioError(null);
    onClose();
  }, [onClose]);

  const canProceedToSelect = clipUuid && name && selectedTag?.id;
  const canSubmit = startTime < endTime && endTime - startTime >= 1;

  return (
    <DialogOverlay
      title={step === "info" ? "Add from Dataset Clip" : "Select Segment"}
      isOpen={isOpen}
      onClose={handleClose}
    >
      <div className={step === "select" ? "w-[600px]" : "w-[400px]"}>
        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-4">
          <div
            className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-medium ${
              step === "info"
                ? "bg-emerald-500 text-white"
                : "bg-stone-200 dark:bg-stone-700 text-stone-600 dark:text-stone-400"
            }`}
          >
            1
          </div>
          <div className="flex-1 h-0.5 bg-stone-200 dark:bg-stone-700" />
          <div
            className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-medium ${
              step === "select"
                ? "bg-emerald-500 text-white"
                : "bg-stone-200 dark:bg-stone-700 text-stone-600 dark:text-stone-400"
            }`}
          >
            2
          </div>
        </div>

        {step === "info" ? (
          /* Step 1: Basic info */
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
                Clip UUID
              </label>
              <input
                type="text"
                value={clipUuid}
                onChange={(e) => setClipUuid(e.target.value)}
                className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
                placeholder="Enter clip UUID"
              />
              <p className="text-xs text-stone-500 mt-1">
                Enter the UUID of the clip from your dataset
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
                Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
                placeholder="Reference sound name"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
                Species Tag
              </label>
              {selectedTag ? (
                <div className="flex items-center gap-2 p-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-stone-50 dark:bg-stone-800">
                  <TagComponent
                    tag={selectedTag}
                    color="emerald"
                    level={3}
                    disabled
                    className="pointer-events-none"
                  />
                  <button
                    type="button"
                    onClick={handleClearTag}
                    className="ml-auto p-1 text-stone-400 hover:text-stone-600 dark:hover:text-stone-300 rounded"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ) : (
                <TagSearchBar
                  onSelectTag={handleTagSelect}
                  onCreateTag={handleTagSelect}
                />
              )}
            </div>

            <div className="flex justify-end gap-2 pt-4">
              <Button type="button" variant="secondary" onClick={handleClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={!canProceedToSelect}
                onClick={handleLoadAudio}
              >
                Load Audio
                <ChevronRight className="w-4 h-4 ml-1" />
              </Button>
            </div>
          </div>
        ) : (
          /* Step 2: Segment selection */
          <div className="space-y-4">
            {audioError ? (
              <div className="p-4 bg-red-50 dark:bg-red-900/20 rounded-lg text-red-600 dark:text-red-400">
                <p className="font-medium">Failed to load audio</p>
                <p className="text-sm mt-1">{audioError}</p>
                <Button
                  variant="secondary"
                  className="mt-3"
                  onClick={handleBack}
                >
                  <ChevronLeft className="w-4 h-4 mr-1" />
                  Back
                </Button>
              </div>
            ) : (
              <>
                <div className="p-3 bg-stone-50 dark:bg-stone-800 rounded-lg">
                  <div className="flex items-center gap-4 text-sm">
                    <div>
                      <span className="text-stone-500 dark:text-stone-400">
                        Clip:
                      </span>{" "}
                      <span className="font-medium font-mono text-xs">
                        {clipUuid.slice(0, 8)}...
                      </span>
                    </div>
                    <div>
                      <span className="text-stone-500 dark:text-stone-400">
                        Name:
                      </span>{" "}
                      <span className="font-medium">{name}</span>
                    </div>
                    {selectedTag && (
                      <TagComponent
                        tag={selectedTag}
                        color="emerald"
                        level={3}
                        disabled
                        className="pointer-events-none"
                      />
                    )}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-2">
                    Select Audio Segment
                  </label>
                  <SpectrogramSegmentSelector
                    audioUrl={audioUrl}
                    onSegmentChange={handleSegmentChange}
                    initialStartTime={startTime}
                    initialEndTime={endTime}
                    height={180}
                  />
                </div>

                <div className="flex justify-between gap-2 pt-4">
                  <Button variant="secondary" onClick={handleBack}>
                    <ChevronLeft className="w-4 h-4 mr-1" />
                    Back
                  </Button>
                  <Button
                    variant="primary"
                    disabled={!canSubmit || isSubmitting}
                    onClick={handleSubmit}
                  >
                    {isSubmitting ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Adding...
                      </>
                    ) : (
                      "Add Reference Sound"
                    )}
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </DialogOverlay>
  );
}

export default function ReferenceSoundsPage() {
  const params = useParams();
  const mlProjectUuid = params.ml_project_uuid as string;
  const mlProject = useContext(MLProjectContext);
  const queryClient = useQueryClient();

  const [showXenoCantoDialog, setShowXenoCantoDialog] = useState(false);
  const [showClipDialog, setShowClipDialog] = useState(false);
  const [showActiveOnly, setShowActiveOnly] = useState(false);

  // Fetch reference sounds
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "reference_sounds", showActiveOnly],
    queryFn: () =>
      api.referenceSounds.getMany(mlProjectUuid, {
        limit: 100,
        is_active: showActiveOnly ? true : undefined,
      }),
    enabled: !!mlProjectUuid,
  });

  const sounds = data?.items || [];

  // Toggle active mutation
  const toggleMutation = useMutation({
    mutationFn: ({
      soundUuid,
      isActive,
    }: {
      soundUuid: string;
      isActive: boolean;
    }) => api.referenceSounds.toggleActive(mlProjectUuid, soundUuid, isActive),
    onSuccess: () => {
      refetch();
      queryClient.invalidateQueries({
        queryKey: ["ml_project", mlProjectUuid],
      });
    },
    onError: () => {
      toast.error("Failed to toggle reference sound");
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (soundUuid: string) =>
      api.referenceSounds.delete(mlProjectUuid, soundUuid),
    onSuccess: () => {
      toast.success("Reference sound deleted");
      refetch();
      queryClient.invalidateQueries({
        queryKey: ["ml_project", mlProjectUuid],
      });
    },
    onError: () => {
      toast.error("Failed to delete reference sound");
    },
  });

  const handleToggle = useCallback(
    (soundUuid: string, currentIsActive: boolean) => {
      toggleMutation.mutate({ soundUuid, isActive: !currentIsActive });
    },
    [toggleMutation],
  );

  const handleDelete = useCallback(
    (soundUuid: string) => {
      deleteMutation.mutate(soundUuid);
    },
    [deleteMutation],
  );

  const handleSuccess = useCallback(() => {
    refetch();
    queryClient.invalidateQueries({ queryKey: ["ml_project", mlProjectUuid] });
  }, [refetch, queryClient, mlProjectUuid]);

  if (isLoading) {
    return <Loading />;
  }

  return (
    <div className="space-y-6">
      {/* Header and Actions */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-stone-900 dark:text-stone-100">
            Reference Sounds
          </h2>
          <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
            Reference sounds are used to find similar audio in the dataset
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            onClick={() => setShowActiveOnly(!showActiveOnly)}
          >
            {showActiveOnly ? "Show All" : "Active Only"}
          </Button>
          <Button variant="secondary" onClick={() => setShowClipDialog(true)}>
            <Database className="w-4 h-4 mr-2" />
            From Clip
          </Button>
          <Button
            variant="primary"
            onClick={() => setShowXenoCantoDialog(true)}
          >
            <Globe className="w-4 h-4 mr-2" />
            From Xeno-Canto
          </Button>
        </div>
      </div>

      {/* Sound Grid */}
      {sounds.length === 0 ? (
        <Empty>
          <Music className="w-12 h-12 mb-4 text-stone-400" />
          <p className="text-lg font-medium">No reference sounds</p>
          <p className="text-sm text-stone-500 mt-1">
            Add reference sounds to start finding similar audio in your dataset
          </p>
          <div className="flex gap-2 mt-4">
            <Button variant="secondary" onClick={() => setShowClipDialog(true)}>
              <Database className="w-4 h-4 mr-2" />
              From Dataset Clip
            </Button>
            <Button
              variant="primary"
              onClick={() => setShowXenoCantoDialog(true)}
            >
              <Globe className="w-4 h-4 mr-2" />
              From Xeno-Canto
            </Button>
          </div>
        </Empty>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {sounds.map((sound) => (
            <ReferenceSoundCard
              key={sound.uuid}
              sound={sound}
              mlProjectUuid={mlProjectUuid}
              onToggle={() => handleToggle(sound.uuid, sound.is_active)}
              onDelete={() => handleDelete(sound.uuid)}
            />
          ))}
        </div>
      )}

      {/* Dialogs */}
      <AddFromXenoCantoDialog
        isOpen={showXenoCantoDialog}
        onClose={() => setShowXenoCantoDialog(false)}
        mlProjectUuid={mlProjectUuid}
        onSuccess={handleSuccess}
      />
      <AddFromClipDialog
        isOpen={showClipDialog}
        onClose={() => setShowClipDialog(false)}
        mlProjectUuid={mlProjectUuid}
        onSuccess={handleSuccess}
      />
    </div>
  );
}
