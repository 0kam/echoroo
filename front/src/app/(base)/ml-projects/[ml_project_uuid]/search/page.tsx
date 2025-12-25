"use client";

/**
 * Search Sessions list page.
 *
 * Displays a list of search sessions with their progress,
 * allows creating new sessions and navigating to session details.
 */
import { useCallback, useContext, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  Plus,
  Search,
  Play,
  CheckCircle,
  Clock,
  ArrowRight,
  Trash2,
  Tag as TagIcon,
  Music,
  Loader2,
} from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import ProgressBar from "@/lib/components/ui/ProgressBar";
import { DialogOverlay } from "@/lib/components/ui/Dialog";
import Link from "@/lib/components/ui/Link";

import type { SearchSession, SearchSessionCreate, ReferenceSound, Tag } from "@/lib/types";

import MLProjectContext from "../context";

function SessionCard({
  session,
  mlProjectUuid,
  onDelete,
}: {
  session: SearchSession;
  mlProjectUuid: string;
  onDelete: () => void;
}) {
  const labeledPercent = session.result_count > 0
    ? Math.round((session.labeled_count / session.result_count) * 100)
    : 0;

  return (
    <Card className="hover:border-emerald-500/50 transition-colors">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <Link href={`/ml-projects/${mlProjectUuid}/search/${session.uuid}`}>
            <h3 className="text-lg font-semibold text-stone-900 dark:text-stone-100 hover:text-emerald-600 dark:hover:text-emerald-400">
              {session.name}
            </h3>
          </Link>
          {session.description && (
            <p className="text-sm text-stone-500 dark:text-stone-400 mt-1 line-clamp-2">
              {session.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {session.is_labeling_complete ? (
            <span className="flex items-center gap-1 px-2 py-1 text-xs bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 rounded-full">
              <CheckCircle className="w-3 h-3" />
              Complete
            </span>
          ) : session.is_search_complete ? (
            <span className="flex items-center gap-1 px-2 py-1 text-xs bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 rounded-full">
              <TagIcon className="w-3 h-3" />
              Labeling
            </span>
          ) : (
            <span className="flex items-center gap-1 px-2 py-1 text-xs bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 rounded-full">
              <Clock className="w-3 h-3" />
              Pending
            </span>
          )}
        </div>
      </div>

      {/* Target tag */}
      <div className="flex items-center gap-2 mt-3 text-sm text-stone-600 dark:text-stone-400">
        <TagIcon className="w-4 h-4" />
        <span>Target: {session.target_tag.key}: {session.target_tag.value}</span>
      </div>

      {/* Reference sounds */}
      {session.reference_sounds.length > 0 && (
        <div className="flex items-center gap-2 mt-2 text-sm text-stone-600 dark:text-stone-400">
          <Music className="w-4 h-4" />
          <span>{session.reference_sounds.length} reference sound(s)</span>
        </div>
      )}

      {/* Progress */}
      {session.is_search_complete && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-sm mb-2">
            <span className="text-stone-500 dark:text-stone-400">
              Labeling Progress
            </span>
            <span className="text-stone-700 dark:text-stone-300">
              {session.labeled_count} / {session.result_count} ({labeledPercent}%)
            </span>
          </div>
          <ProgressBar
            total={session.result_count}
            complete={session.labeled_count}
            className="mb-0"
          />
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between mt-4 pt-3 border-t border-stone-200 dark:border-stone-700">
        <Button
          variant="danger"
          mode="text"
          onClick={(e) => {
            e.preventDefault();
            onDelete();
          }}
        >
          <Trash2 className="w-4 h-4" />
        </Button>
        <Link href={`/ml-projects/${mlProjectUuid}/search/${session.uuid}`}>
          <Button variant="primary" mode="text">
            {session.is_search_complete ? "Continue Labeling" : "View Session"}
            <ArrowRight className="w-4 h-4 ml-1" />
          </Button>
        </Link>
      </div>
    </Card>
  );
}

function CreateSessionDialog({
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
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [targetTagId, setTargetTagId] = useState<number | null>(null);
  const [selectedSoundIds, setSelectedSoundIds] = useState<string[]>([]);
  const [similarityThreshold, setSimilarityThreshold] = useState("0.7");
  const [maxResults, setMaxResults] = useState("1000");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch available tags
  const { data: tagsData } = useQuery({
    queryKey: ["tags"],
    queryFn: () => api.tags.get({ limit: 100 }),
  });
  const tags = tagsData?.items || [];

  // Fetch reference sounds
  const { data: soundsData } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "reference_sounds", "active"],
    queryFn: () => api.referenceSounds.getMany(mlProjectUuid, { is_active: true, limit: 100 }),
  });
  const sounds = soundsData?.items || [];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !targetTagId || selectedSoundIds.length === 0) return;

    setIsSubmitting(true);
    try {
      await api.searchSessions.create(mlProjectUuid, {
        name,
        description: description || undefined,
        target_tag_id: targetTagId,
        reference_sound_ids: selectedSoundIds,
        similarity_threshold: parseFloat(similarityThreshold),
        max_results: parseInt(maxResults),
      });
      toast.success("Search session created");
      setName("");
      setDescription("");
      setTargetTagId(null);
      setSelectedSoundIds([]);
      setSimilarityThreshold("0.7");
      setMaxResults("1000");
      onSuccess();
      onClose();
    } catch (error) {
      toast.error("Failed to create search session");
      console.error(error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const toggleSound = (uuid: string) => {
    setSelectedSoundIds((prev) =>
      prev.includes(uuid)
        ? prev.filter((id) => id !== uuid)
        : [...prev, uuid]
    );
  };

  return (
    <DialogOverlay
      title="Create Search Session"
      isOpen={isOpen}
      onClose={onClose}
    >
      <form onSubmit={handleSubmit} className="w-[500px] space-y-4 max-h-[70vh] overflow-y-auto">
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Session Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            placeholder="e.g., Bird song search session 1"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Description (optional)
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            placeholder="Describe what you're searching for..."
            rows={2}
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Target Tag
          </label>
          <select
            value={targetTagId || ""}
            onChange={(e) => setTargetTagId(Number(e.target.value) || null)}
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

        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Reference Sounds
          </label>
          {sounds.length === 0 ? (
            <p className="text-sm text-stone-500">
              No active reference sounds available. Add reference sounds first.
            </p>
          ) : (
            <div className="space-y-2 max-h-40 overflow-y-auto border border-stone-200 dark:border-stone-700 rounded-lg p-2">
              {sounds.map((sound) => (
                <label
                  key={sound.uuid}
                  className="flex items-center gap-2 p-2 rounded hover:bg-stone-100 dark:hover:bg-stone-700 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selectedSoundIds.includes(sound.uuid)}
                    onChange={() => toggleSound(sound.uuid)}
                    className="rounded border-stone-300 text-emerald-600 focus:ring-emerald-500"
                  />
                  <span className="text-sm text-stone-700 dark:text-stone-300">
                    {sound.name}
                  </span>
                  <span className="text-xs text-stone-500 ml-auto">
                    {sound.tag.key}: {sound.tag.value}
                  </span>
                </label>
              ))}
            </div>
          )}
          {selectedSoundIds.length > 0 && (
            <p className="text-xs text-stone-500 mt-1">
              {selectedSoundIds.length} sound(s) selected
            </p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
              Similarity Threshold
            </label>
            <input
              type="number"
              step="0.01"
              min="0"
              max="1"
              value={similarityThreshold}
              onChange={(e) => setSimilarityThreshold(e.target.value)}
              className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
              Max Results
            </label>
            <input
              type="number"
              min="1"
              value={maxResults}
              onChange={(e) => setMaxResults(e.target.value)}
              className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
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
            disabled={!name || !targetTagId || selectedSoundIds.length === 0 || isSubmitting}
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Creating...
              </>
            ) : (
              "Create Session"
            )}
          </Button>
        </div>
      </form>
    </DialogOverlay>
  );
}

export default function SearchSessionsPage() {
  const params = useParams();
  const router = useRouter();
  const mlProjectUuid = params.ml_project_uuid as string;
  const mlProject = useContext(MLProjectContext);
  const queryClient = useQueryClient();

  const [showCreateDialog, setShowCreateDialog] = useState(false);

  // Fetch search sessions
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_sessions"],
    queryFn: () => api.searchSessions.getMany(mlProjectUuid, { limit: 100 }),
    enabled: !!mlProjectUuid,
  });

  const sessions = data?.items || [];

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (sessionUuid: string) =>
      api.searchSessions.delete(mlProjectUuid, sessionUuid),
    onSuccess: () => {
      toast.success("Search session deleted");
      refetch();
      queryClient.invalidateQueries({ queryKey: ["ml_project", mlProjectUuid] });
    },
    onError: () => {
      toast.error("Failed to delete search session");
    },
  });

  const handleDelete = useCallback(
    (sessionUuid: string) => {
      if (confirm("Are you sure you want to delete this search session?")) {
        deleteMutation.mutate(sessionUuid);
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
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-stone-900 dark:text-stone-100">
            Search Sessions
          </h2>
          <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
            Search for similar sounds in the dataset using reference sounds
          </p>
        </div>
        <Button variant="primary" onClick={() => setShowCreateDialog(true)}>
          <Plus className="w-4 h-4 mr-2" />
          New Search Session
        </Button>
      </div>

      {/* Sessions List */}
      {sessions.length === 0 ? (
        <Empty>
          <Search className="w-12 h-12 mb-4 text-stone-400" />
          <p className="text-lg font-medium">No search sessions</p>
          <p className="text-sm text-stone-500 mt-1">
            Create a search session to find similar sounds in your dataset
          </p>
          <Button
            variant="primary"
            className="mt-4"
            onClick={() => setShowCreateDialog(true)}
          >
            <Plus className="w-4 h-4 mr-2" />
            Create Search Session
          </Button>
        </Empty>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {sessions.map((session) => (
            <SessionCard
              key={session.uuid}
              session={session}
              mlProjectUuid={mlProjectUuid}
              onDelete={() => handleDelete(session.uuid)}
            />
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <CreateSessionDialog
        isOpen={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        mlProjectUuid={mlProjectUuid}
        onSuccess={handleSuccess}
      />
    </div>
  );
}
