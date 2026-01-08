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
  ChevronDown,
  ChevronUp,
  Settings,
} from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import ProgressBar from "@/lib/components/ui/ProgressBar";
import { DialogOverlay } from "@/lib/components/ui/Dialog";
import Link from "@/lib/components/ui/Link";

import type { SearchSession, ReferenceSound } from "@/lib/types";

import MLProjectContext from "../context";

// Generate a color from tag_id if no color is provided
function generateTagColor(tagId: number): string {
  const colors = [
    "#10b981", // emerald-500
    "#3b82f6", // blue-500
    "#8b5cf6", // violet-500
    "#f59e0b", // amber-500
    "#ec4899", // pink-500
    "#06b6d4", // cyan-500
    "#84cc16", // lime-500
    "#f97316", // orange-500
    "#6366f1", // indigo-500
  ];
  return colors[tagId % colors.length];
}

function SessionCard({
  session,
  mlProjectUuid,
  onDelete,
}: {
  session: SearchSession;
  mlProjectUuid: string;
  onDelete: () => void;
}) {
  const labeledPercent = session.total_results > 0
    ? Math.round((session.labeled_count / session.total_results) * 100)
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
          {session.is_search_complete ? (
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

      {/* Target tags */}
      {session.target_tags.length > 0 && (
        <div className="flex items-center gap-2 mt-3 text-sm text-stone-600 dark:text-stone-400">
          <TagIcon className="w-4 h-4" />
          <div className="flex flex-wrap gap-1">
            {session.target_tags.map((tt) => (
              <span key={tt.tag_id} className="bg-stone-100 dark:bg-stone-800 px-1.5 py-0.5 rounded text-xs">
                {tt.tag.vernacular_name || tt.tag.canonical_name}
              </span>
            ))}
          </div>
        </div>
      )}

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
              {session.labeled_count} / {session.total_results} ({labeledPercent}%)
            </span>
          </div>
          <ProgressBar
            total={session.total_results}
            segments={[
              // Each tag with its color
              ...Object.entries(session.tag_counts).map(([tagIdStr, count]) => {
                const tagId = parseInt(tagIdStr);
                const targetTag = session.target_tags.find((t) => t.tag_id === tagId);
                const color = generateTagColor(tagId);
                const displayName = targetTag
                  ? targetTag.tag.vernacular_name || targetTag.tag.canonical_name || targetTag.tag.value
                  : `Tag ${tagId}`;
                return { count, color, label: displayName };
              }),
              // Negative
              { count: session.negative_count, color: '#ef4444', label: 'Negative' },
              // Uncertain
              { count: session.uncertain_count, color: '#f59e0b', label: 'Uncertain' },
              // Unlabeled
              { count: session.unlabeled_count, color: '#3b82f6', label: 'Unlabeled' },
            ]}
            className="mb-0"
          />
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between mt-4 pt-3 border-t border-stone-200 dark:border-stone-700">
        <Button
          type="button"
          variant="danger"
          mode="text"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onDelete();
          }}
        >
          <Trash2 className="w-4 h-4" />
        </Button>
        <Link href={`/ml-projects/${mlProjectUuid}/search/${session.uuid}`}>
          <Button type="button" variant="primary" mode="text">
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
  const [selectedSoundIds, setSelectedSoundIds] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Active Learning parameters
  const [easyPositiveK, setEasyPositiveK] = useState("5");
  const [boundaryN, setBoundaryN] = useState("200");
  const [boundaryM, setBoundaryM] = useState("10");
  const [othersP, setOthersP] = useState("20");
  const [distanceMetric, setDistanceMetric] = useState<"cosine" | "euclidean">("cosine");

  // Fetch reference sounds
  const { data: soundsData } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "reference_sounds", "active"],
    queryFn: () => api.referenceSounds.getMany(mlProjectUuid, { is_active: true, limit: 100 }),
  });
  const sounds = soundsData?.items || [];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || selectedSoundIds.length === 0) return;

    setIsSubmitting(true);
    try {
      await api.searchSessions.create(mlProjectUuid, {
        name,
        description: description || undefined,
        reference_sound_ids: selectedSoundIds,
        easy_positive_k: parseInt(easyPositiveK),
        boundary_n: parseInt(boundaryN),
        boundary_m: parseInt(boundaryM),
        others_p: parseInt(othersP),
        distance_metric: distanceMetric,
      });
      toast.success("Search session created");
      setName("");
      setDescription("");
      setSelectedSoundIds([]);
      setEasyPositiveK("5");
      setBoundaryN("200");
      setBoundaryM("10");
      setOthersP("20");
      setDistanceMetric("cosine");
      setShowAdvanced(false);
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
                  <div className="flex-1 min-w-0">
                    <span className="text-sm text-stone-700 dark:text-stone-300">
                      {sound.name}
                    </span>
                    <div className="text-xs text-stone-500 truncate">
                      {sound.tag.vernacular_name && (
                        <span>{sound.tag.vernacular_name}</span>
                      )}
                      {sound.tag.vernacular_name && sound.tag.canonical_name && " · "}
                      {sound.tag.canonical_name && (
                        <span className="italic">{sound.tag.canonical_name}</span>
                      )}
                    </div>
                    <div className="text-xs text-stone-400 dark:text-stone-600">
                      {sound.source === "xeno_canto" && sound.xeno_canto_id}
                      {sound.source === "clip" && "Dataset Clip"}
                      {sound.source === "upload" && "Custom Upload"}
                      {" · "}
                      {(sound.end_time - sound.start_time).toFixed(1)}s
                    </div>
                  </div>
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

        {/* Advanced Settings (Collapsible) */}
        <div className="border border-stone-200 dark:border-stone-700 rounded-lg overflow-hidden">
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="w-full flex items-center justify-between px-4 py-3 bg-stone-50 dark:bg-stone-800/50 hover:bg-stone-100 dark:hover:bg-stone-800 transition-colors"
          >
            <div className="flex items-center gap-2 text-sm font-medium text-stone-700 dark:text-stone-300">
              <Settings className="w-4 h-4" />
              Advanced Settings
            </div>
            {showAdvanced ? (
              <ChevronUp className="w-4 h-4 text-stone-500" />
            ) : (
              <ChevronDown className="w-4 h-4 text-stone-500" />
            )}
          </button>

          {showAdvanced && (
            <div className="p-4 space-y-4 border-t border-stone-200 dark:border-stone-700">
              <p className="text-xs text-stone-500 dark:text-stone-400 mb-3">
                Configure Active Learning sampling parameters for diverse result selection.
              </p>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
                    Easy Positives (k)
                  </label>
                  <input
                    type="number"
                    min="0"
                    value={easyPositiveK}
                    onChange={(e) => setEasyPositiveK(e.target.value)}
                    placeholder="5"
                    className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
                  />
                  <p className="text-xs text-stone-400 mt-1">
                    Top-k most similar clips per reference
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
                    Boundary Pool (n)
                  </label>
                  <input
                    type="number"
                    min="0"
                    value={boundaryN}
                    onChange={(e) => setBoundaryN(e.target.value)}
                    placeholder="200"
                    className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
                  />
                  <p className="text-xs text-stone-400 mt-1">
                    Number of candidates in boundary zone
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
                    Boundary Samples (m)
                  </label>
                  <input
                    type="number"
                    min="0"
                    value={boundaryM}
                    onChange={(e) => setBoundaryM(e.target.value)}
                    placeholder="10"
                    className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
                  />
                  <p className="text-xs text-stone-400 mt-1">
                    Random samples from boundary zone
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
                    Others (p)
                  </label>
                  <input
                    type="number"
                    min="0"
                    value={othersP}
                    onChange={(e) => setOthersP(e.target.value)}
                    placeholder="20"
                    className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
                  />
                  <p className="text-xs text-stone-400 mt-1">
                    Diverse samples using farthest-first selection
                  </p>
                </div>
              </div>

              {/* Distance Metric */}
              <div className="mt-4">
                <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-2">
                  Distance Metric
                </label>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="distance_metric"
                      value="cosine"
                      checked={distanceMetric === "cosine"}
                      onChange={() => setDistanceMetric("cosine")}
                      className="text-emerald-600"
                    />
                    <span className="text-sm text-stone-700 dark:text-stone-300">Cosine Similarity (Recommended)</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="distance_metric"
                      value="euclidean"
                      checked={distanceMetric === "euclidean"}
                      onChange={() => setDistanceMetric("euclidean")}
                      className="text-emerald-600"
                    />
                    <span className="text-sm text-stone-700 dark:text-stone-300">Euclidean Distance</span>
                  </label>
                </div>
                <p className="text-xs text-stone-400 mt-1">
                  Method for measuring similarity between audio embeddings
                </p>
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={!name || selectedSoundIds.length === 0 || isSubmitting}
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
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

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
      setDeleteTarget(sessionUuid);
    },
    [],
  );

  const confirmDelete = useCallback(() => {
    if (deleteTarget) {
      deleteMutation.mutate(deleteTarget);
      setDeleteTarget(null);
    }
  }, [deleteTarget, deleteMutation]);

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

      {/* Delete Confirmation Dialog */}
      <DialogOverlay
        title="Delete Search Session"
        isOpen={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
      >
        <div className="space-y-4">
          <p className="text-stone-600 dark:text-stone-400">
            Are you sure you want to delete this search session? This action cannot be undone.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button mode="text" variant="danger" onClick={confirmDelete}>
              <Trash2 className="w-4 h-4 mr-2" />
              Delete
            </Button>
          </div>
        </div>
      </DialogOverlay>
    </div>
  );
}
