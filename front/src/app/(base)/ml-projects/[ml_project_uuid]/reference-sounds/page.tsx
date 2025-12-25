"use client";

/**
 * Reference Sounds management page.
 *
 * Displays a list of reference sounds with spectrogram thumbnails.
 * Allows adding reference sounds from Xeno-Canto or dataset clips,
 * toggling active/inactive state, and deleting sounds.
 */
import { useCallback, useContext, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  Plus,
  Music,
  Globe,
  Database,
  ToggleLeft,
  ToggleRight,
  Trash2,
  ExternalLink,
  Clock,
  CheckCircle,
  XCircle,
  Play,
  Loader2,
} from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import { DialogOverlay } from "@/lib/components/ui/Dialog";

import type { ReferenceSound, ReferenceSoundFromXenoCanto, ReferenceSoundFromClip, Tag } from "@/lib/types";

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
  const [isPlaying, setIsPlaying] = useState(false);

  const sourceIcon = {
    xeno_canto: <Globe className="w-4 h-4" />,
    custom_upload: <Music className="w-4 h-4" />,
    dataset_clip: <Database className="w-4 h-4" />,
  };

  const sourceLabel = {
    xeno_canto: "Xeno-Canto",
    custom_upload: "Custom Upload",
    dataset_clip: "Dataset Clip",
  };

  return (
    <Card className="relative">
      {/* Spectrogram thumbnail placeholder */}
      <div className="aspect-[3/1] bg-stone-100 dark:bg-stone-800 rounded-lg mb-3 flex items-center justify-center">
        {/* In a real implementation, this would show a spectrogram image */}
        <div className="text-stone-400 flex flex-col items-center gap-2">
          <Music className="w-8 h-8" />
          <span className="text-xs">
            {sound.start_time.toFixed(2)}s - {sound.end_time.toFixed(2)}s
          </span>
        </div>
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
              href={sound.xeno_canto_url || `https://xeno-canto.org/${sound.xeno_canto_id}`}
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
            {sound.tag.key}: {sound.tag.value}
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
        <Button
          variant="danger"
          mode="text"
          onClick={onDelete}
        >
          <Trash2 className="w-4 h-4" />
        </Button>
      </div>
    </Card>
  );
}

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
  const [xenoCantoId, setXenoCantoId] = useState("");
  const [name, setName] = useState("");
  const [tagId, setTagId] = useState<number | null>(null);
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch available tags
  const { data: tagsData } = useQuery({
    queryKey: ["tags"],
    queryFn: () => api.tags.get({ limit: 100 }),
  });
  const tags = tagsData?.items || [];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!xenoCantoId || !name || !tagId) return;

    setIsSubmitting(true);
    try {
      await api.referenceSounds.createFromXenoCanto(mlProjectUuid, {
        xeno_canto_id: xenoCantoId,
        name,
        tag_id: tagId,
        start_time: startTime ? parseFloat(startTime) : undefined,
        end_time: endTime ? parseFloat(endTime) : undefined,
      });
      toast.success("Reference sound added from Xeno-Canto");
      setXenoCantoId("");
      setName("");
      setTagId(null);
      setStartTime("");
      setEndTime("");
      onSuccess();
      onClose();
    } catch (error) {
      toast.error("Failed to add reference sound");
      console.error(error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <DialogOverlay
      title="Add from Xeno-Canto"
      isOpen={isOpen}
      onClose={onClose}
    >
      <form onSubmit={handleSubmit} className="w-[400px] space-y-4">
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
            required
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
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Species Tag
          </label>
          <select
            value={tagId || ""}
            onChange={(e) => setTagId(Number(e.target.value) || null)}
            className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            required
          >
            <option value="">Select a tag</option>
            {tags.map((tag: Tag) => (
              <option key={`${tag.key}:${tag.value}`} value={tag.id}>
                {tag.key}: {tag.value}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
              Start Time (s)
            </label>
            <input
              type="number"
              step="0.01"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
              placeholder="0.00"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
              End Time (s)
            </label>
            <input
              type="number"
              step="0.01"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
              placeholder="5.00"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={!xenoCantoId || !name || !tagId || isSubmitting}
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
      </form>
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
  const [clipId, setClipId] = useState("");
  const [name, setName] = useState("");
  const [tagId, setTagId] = useState<number | null>(null);
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch available tags
  const { data: tagsData } = useQuery({
    queryKey: ["tags"],
    queryFn: () => api.tags.get({ limit: 100 }),
  });
  const tags = tagsData?.items || [];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!clipId || !name || !tagId) return;

    setIsSubmitting(true);
    try {
      await api.referenceSounds.createFromClip(mlProjectUuid, {
        clip_id: parseInt(clipId),
        name,
        tag_id: tagId,
        start_time: startTime ? parseFloat(startTime) : undefined,
        end_time: endTime ? parseFloat(endTime) : undefined,
      });
      toast.success("Reference sound added from clip");
      setClipId("");
      setName("");
      setTagId(null);
      setStartTime("");
      setEndTime("");
      onSuccess();
      onClose();
    } catch (error) {
      toast.error("Failed to add reference sound");
      console.error(error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <DialogOverlay
      title="Add from Dataset Clip"
      isOpen={isOpen}
      onClose={onClose}
    >
      <form onSubmit={handleSubmit} className="w-[400px] space-y-4">
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Clip ID
          </label>
          <input
            type="number"
            value={clipId}
            onChange={(e) => setClipId(e.target.value)}
            className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            placeholder="Enter clip ID"
            required
          />
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
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Species Tag
          </label>
          <select
            value={tagId || ""}
            onChange={(e) => setTagId(Number(e.target.value) || null)}
            className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            required
          >
            <option value="">Select a tag</option>
            {tags.map((tag: Tag) => (
              <option key={`${tag.key}:${tag.value}`} value={tag.id}>
                {tag.key}: {tag.value}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
              Start Time (s)
            </label>
            <input
              type="number"
              step="0.01"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
              placeholder="0.00"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
              End Time (s)
            </label>
            <input
              type="number"
              step="0.01"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
              placeholder="5.00"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={!clipId || !name || !tagId || isSubmitting}
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
      </form>
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
    mutationFn: (soundUuid: string) =>
      api.referenceSounds.toggleActive(mlProjectUuid, soundUuid),
    onSuccess: () => {
      refetch();
      queryClient.invalidateQueries({ queryKey: ["ml_project", mlProjectUuid] });
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
      queryClient.invalidateQueries({ queryKey: ["ml_project", mlProjectUuid] });
    },
    onError: () => {
      toast.error("Failed to delete reference sound");
    },
  });

  const handleToggle = useCallback(
    (soundUuid: string) => {
      toggleMutation.mutate(soundUuid);
    },
    [toggleMutation],
  );

  const handleDelete = useCallback(
    (soundUuid: string) => {
      if (confirm("Are you sure you want to delete this reference sound?")) {
        deleteMutation.mutate(soundUuid);
      }
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
          <Button
            variant="secondary"
            onClick={() => setShowClipDialog(true)}
          >
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
            <Button
              variant="secondary"
              onClick={() => setShowClipDialog(true)}
            >
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
              onToggle={() => handleToggle(sound.uuid)}
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
