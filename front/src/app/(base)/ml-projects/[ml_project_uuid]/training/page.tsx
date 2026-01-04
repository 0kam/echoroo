"use client";

/**
 * Custom Models list page.
 *
 * Displays a list of trained models with their status and metrics.
 * Allows creating new models and starting training.
 */
import { useCallback, useContext, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  Plus,
  Cpu,
  Play,
  CheckCircle,
  XCircle,
  Clock,
  Trash2,
  Loader2,
  BarChart2,
  Target,
  Percent,
  Layers,
  Archive,
  Rocket,
} from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import ProgressBar from "@/lib/components/ui/ProgressBar";
import { DialogOverlay } from "@/lib/components/ui/Dialog";

import type {
  CustomModel,
  CustomModelCreate,
  CustomModelStatus,
  CustomModelType,
  SearchSession,
  Tag,
} from "@/lib/types";

import MLProjectContext from "../context";

// Status badge colors
const STATUS_COLORS: Record<CustomModelStatus, string> = {
  draft: "bg-stone-200 text-stone-700 dark:bg-stone-700 dark:text-stone-300",
  training: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  trained: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  failed: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  deployed: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
  archived: "bg-stone-300 text-stone-600 dark:bg-stone-600 dark:text-stone-400",
};

const STATUS_ICONS: Record<CustomModelStatus, React.ReactNode> = {
  draft: <Clock className="w-4 h-4" />,
  training: <Loader2 className="w-4 h-4 animate-spin" />,
  trained: <CheckCircle className="w-4 h-4" />,
  failed: <XCircle className="w-4 h-4" />,
  deployed: <Rocket className="w-4 h-4" />,
  archived: <Archive className="w-4 h-4" />,
};

const MODEL_TYPE_LABELS: Record<CustomModelType, string> = {
  logistic_regression: "Logistic Regression",
  svm_linear: "Linear SVM",
  mlp_small: "MLP (Small)",
  mlp_medium: "MLP (Medium)",
  random_forest: "Random Forest",
};

function StatusBadge({ status }: { status: CustomModelStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-full ${STATUS_COLORS[status]}`}
    >
      {STATUS_ICONS[status]}
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function MetricCard({ label, value, icon }: { label: string; value: string | number | null; icon: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 p-2 bg-stone-50 dark:bg-stone-800 rounded-lg">
      <div className="text-stone-400">{icon}</div>
      <div>
        <p className="text-xs text-stone-500">{label}</p>
        <p className="text-sm font-medium">
          {value !== null ? (typeof value === "number" ? `${(value * 100).toFixed(1)}%` : value) : "-"}
        </p>
      </div>
    </div>
  );
}

function ModelCard({
  model,
  mlProjectUuid,
  onTrain,
  onDeploy,
  onArchive,
  onDelete,
}: {
  model: CustomModel;
  mlProjectUuid: string;
  onTrain: () => void;
  onDeploy: () => void;
  onArchive: () => void;
  onDelete: () => void;
}) {
  return (
    <Card>
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
            {model.name}
          </h3>
          {model.description && (
            <p className="text-sm text-stone-500 dark:text-stone-400 mt-1 line-clamp-2">
              {model.description}
            </p>
          )}
        </div>
        <StatusBadge status={model.status} />
      </div>

      {/* Model info */}
      <div className="space-y-2 text-sm text-stone-600 dark:text-stone-400 mb-4">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4" />
          <span>{MODEL_TYPE_LABELS[model.model_type]}</span>
        </div>
        <div className="flex items-center gap-2">
          <Target className="w-4 h-4" />
          <span>Target: {model.target_tag.key}: {model.target_tag.value}</span>
        </div>
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4" />
          <span>
            Training: {model.training_samples} samples | Validation: {model.validation_samples} samples
          </span>
        </div>
      </div>

      {/* Metrics (if trained) */}
      {model.status === "trained" || model.status === "deployed" ? (
        <div className="grid grid-cols-4 gap-2 mb-4">
          <MetricCard
            label="Accuracy"
            value={model.accuracy}
            icon={<BarChart2 className="w-4 h-4" />}
          />
          <MetricCard
            label="Precision"
            value={model.precision}
            icon={<Target className="w-4 h-4" />}
          />
          <MetricCard
            label="Recall"
            value={model.recall}
            icon={<Percent className="w-4 h-4" />}
          />
          <MetricCard
            label="F1 Score"
            value={model.f1_score}
            icon={<BarChart2 className="w-4 h-4" />}
          />
        </div>
      ) : null}

      {/* Error message (if failed) */}
      {model.status === "failed" && model.error_message && (
        <div className="p-3 mb-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
          <p className="text-sm text-red-600 dark:text-red-400">{model.error_message}</p>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between pt-3 border-t border-stone-200 dark:border-stone-700">
        <Button variant="danger" mode="text" onClick={onDelete}>
          <Trash2 className="w-4 h-4" />
        </Button>
        <div className="flex items-center gap-2">
          {model.status === "draft" && (
            <Button variant="primary" onClick={onTrain}>
              <Play className="w-4 h-4 mr-1" />
              Start Training
            </Button>
          )}
          {model.status === "trained" && (
            <>
              <Button variant="secondary" onClick={onArchive}>
                <Archive className="w-4 h-4 mr-1" />
                Archive
              </Button>
              <Button variant="primary" onClick={onDeploy}>
                <Rocket className="w-4 h-4 mr-1" />
                Deploy
              </Button>
            </>
          )}
          {model.status === "deployed" && (
            <Button variant="secondary" onClick={onArchive}>
              <Archive className="w-4 h-4 mr-1" />
              Archive
            </Button>
          )}
          {model.status === "failed" && (
            <Button variant="primary" onClick={onTrain}>
              <Play className="w-4 h-4 mr-1" />
              Retry Training
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}

// Training data source type
type TrainingSourceType = "search_session" | "annotation_project";

function CreateModelDialog({
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
  const [modelType, setModelType] = useState<CustomModelType>("logistic_regression");
  const [sourceType, setSourceType] = useState<TrainingSourceType>("search_session");
  const [selectedSessionIds, setSelectedSessionIds] = useState<string[]>([]);
  const [selectedAnnotationProjectIds, setSelectedAnnotationProjectIds] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch available tags
  const { data: tagsData } = useQuery({
    queryKey: ["tags"],
    queryFn: () => api.tags.get({ limit: 100 }),
  });
  const tags = tagsData?.items || [];

  // Fetch search sessions
  const { data: sessionsData } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_sessions"],
    queryFn: () => api.searchSessions.getMany(mlProjectUuid, { limit: 100 }),
  });
  const sessions = (sessionsData?.items || []).filter(
    (s) => s.is_search_complete && s.labeled_count > 0
  );

  // Fetch annotation projects for this ML project
  const { data: annotationProjectsData } = useQuery({
    queryKey: ["ml_project_annotation_projects", mlProjectUuid],
    queryFn: () => api.mlProjects.annotationProjects.list(mlProjectUuid),
    enabled: !!mlProjectUuid,
  });
  const annotationProjects = annotationProjectsData || [];

  // Check if any training data is selected
  const hasTrainingData =
    (sourceType === "search_session" && selectedSessionIds.length > 0) ||
    (sourceType === "annotation_project" && selectedAnnotationProjectIds.length > 0);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !targetTagId || !hasTrainingData) return;

    setIsSubmitting(true);
    try {
      await api.customModels.create(mlProjectUuid, {
        name,
        description: description || undefined,
        target_tag_id: targetTagId,
        model_type: modelType,
        training_session_ids: sourceType === "search_session" ? selectedSessionIds : [],
        annotation_project_uuids: sourceType === "annotation_project" ? selectedAnnotationProjectIds : [],
      });
      toast.success("Model created");
      setName("");
      setDescription("");
      setTargetTagId(null);
      setModelType("logistic_regression");
      setSourceType("search_session");
      setSelectedSessionIds([]);
      setSelectedAnnotationProjectIds([]);
      onSuccess();
      onClose();
    } catch (error) {
      toast.error("Failed to create model");
      console.error(error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const toggleSession = (uuid: string) => {
    setSelectedSessionIds((prev) =>
      prev.includes(uuid) ? prev.filter((id) => id !== uuid) : [...prev, uuid]
    );
  };

  const toggleAnnotationProject = (uuid: string) => {
    setSelectedAnnotationProjectIds((prev) =>
      prev.includes(uuid) ? prev.filter((id) => id !== uuid) : [...prev, uuid]
    );
  };

  const modelTypes: { value: CustomModelType; label: string }[] = [
    { value: "logistic_regression", label: "Logistic Regression (fast, interpretable)" },
    { value: "svm_linear", label: "Linear SVM (good for small datasets)" },
    { value: "mlp_small", label: "MLP Small (neural network, balanced)" },
    { value: "mlp_medium", label: "MLP Medium (neural network, more capacity)" },
    { value: "random_forest", label: "Random Forest (ensemble, robust)" },
  ];

  return (
    <DialogOverlay title="Create Custom Model" isOpen={isOpen} onClose={onClose}>
      <form onSubmit={handleSubmit} className="w-[500px] space-y-4 max-h-[70vh] overflow-y-auto">
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
            Model Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            placeholder="e.g., Bird Song Detector v1"
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
            placeholder="Describe your model..."
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
            Model Type
          </label>
          <select
            value={modelType}
            onChange={(e) => setModelType(e.target.value as CustomModelType)}
            className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
          >
            {modelTypes.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
        </div>

        {/* Training Data Source Type Selection */}
        <div>
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-2">
            Training Data Source
          </label>
          <div className="flex gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="sourceType"
                value="search_session"
                checked={sourceType === "search_session"}
                onChange={() => setSourceType("search_session")}
                className="text-emerald-600 focus:ring-emerald-500"
              />
              <span className="text-sm text-stone-700 dark:text-stone-300">Search Sessions</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name="sourceType"
                value="annotation_project"
                checked={sourceType === "annotation_project"}
                onChange={() => setSourceType("annotation_project")}
                className="text-emerald-600 focus:ring-emerald-500"
              />
              <span className="text-sm text-stone-700 dark:text-stone-300">Annotation Projects</span>
            </label>
          </div>
        </div>

        {/* Search Sessions Selection */}
        {sourceType === "search_session" && (
          <div>
            <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
              Select Search Sessions
            </label>
            {sessions.length === 0 ? (
              <p className="text-sm text-stone-500">
                No completed search sessions with labeled data available.
              </p>
            ) : (
              <div className="space-y-2 max-h-40 overflow-y-auto border border-stone-200 dark:border-stone-700 rounded-lg p-2">
                {sessions.map((session) => (
                  <label
                    key={session.uuid}
                    className="flex items-center gap-2 p-2 rounded hover:bg-stone-100 dark:hover:bg-stone-700 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={selectedSessionIds.includes(session.uuid)}
                      onChange={() => toggleSession(session.uuid)}
                      className="rounded border-stone-300 text-emerald-600 focus:ring-emerald-500"
                    />
                    <div className="flex-1">
                      <span className="text-sm text-stone-700 dark:text-stone-300">
                        {session.name}
                      </span>
                      <span className="text-xs text-stone-500 ml-2">
                        ({session.labeled_count} labeled)
                      </span>
                    </div>
                  </label>
                ))}
              </div>
            )}
            {selectedSessionIds.length > 0 && (
              <p className="text-xs text-stone-500 mt-1">
                {selectedSessionIds.length} session(s) selected
              </p>
            )}
          </div>
        )}

        {/* Annotation Projects Selection */}
        {sourceType === "annotation_project" && (
          <div>
            <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
              Select Annotation Projects
            </label>
            {annotationProjects.length === 0 ? (
              <div className="text-sm text-stone-500 p-3 bg-stone-50 dark:bg-stone-800 rounded-lg">
                <p>No annotation projects available.</p>
                <p className="mt-1 text-xs">
                  Create annotation projects by exporting curated search results first.
                </p>
              </div>
            ) : (
              <div className="space-y-2 max-h-40 overflow-y-auto border border-stone-200 dark:border-stone-700 rounded-lg p-2">
                {annotationProjects.map((project) => (
                  <label
                    key={project.uuid}
                    className="flex items-center gap-2 p-2 rounded hover:bg-stone-100 dark:hover:bg-stone-700 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={selectedAnnotationProjectIds.includes(project.uuid)}
                      onChange={() => toggleAnnotationProject(project.uuid)}
                      className="rounded border-stone-300 text-emerald-600 focus:ring-emerald-500"
                    />
                    <div className="flex-1">
                      <span className="text-sm text-stone-700 dark:text-stone-300">
                        {project.name}
                      </span>
                      <span className="text-xs text-stone-500 ml-2">
                        ({project.clip_count} clips)
                      </span>
                    </div>
                  </label>
                ))}
              </div>
            )}
            {selectedAnnotationProjectIds.length > 0 && (
              <p className="text-xs text-stone-500 mt-1">
                {selectedAnnotationProjectIds.length} project(s) selected
              </p>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={!name || !targetTagId || !hasTrainingData || isSubmitting}
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Creating...
              </>
            ) : (
              "Create Model"
            )}
          </Button>
        </div>
      </form>
    </DialogOverlay>
  );
}

export default function ModelsPage() {
  const params = useParams();
  const mlProjectUuid = params.ml_project_uuid as string;
  const mlProject = useContext(MLProjectContext);
  const queryClient = useQueryClient();

  const [showCreateDialog, setShowCreateDialog] = useState(false);

  // Fetch models
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "custom_models"],
    queryFn: () => api.customModels.getMany(mlProjectUuid, { limit: 100 }),
    enabled: !!mlProjectUuid,
  });

  const models = data?.items || [];

  // Mutations
  const trainMutation = useMutation({
    mutationFn: (modelUuid: string) =>
      api.customModels.startTraining(mlProjectUuid, modelUuid),
    onSuccess: () => {
      toast.success("Training started");
      refetch();
    },
    onError: () => {
      toast.error("Failed to start training");
    },
  });

  const deployMutation = useMutation({
    mutationFn: (modelUuid: string) =>
      api.customModels.deploy(mlProjectUuid, modelUuid),
    onSuccess: () => {
      toast.success("Model deployed");
      refetch();
    },
    onError: () => {
      toast.error("Failed to deploy model");
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (modelUuid: string) =>
      api.customModels.archive(mlProjectUuid, modelUuid),
    onSuccess: () => {
      toast.success("Model archived");
      refetch();
    },
    onError: () => {
      toast.error("Failed to archive model");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (modelUuid: string) =>
      api.customModels.delete(mlProjectUuid, modelUuid),
    onSuccess: () => {
      toast.success("Model deleted");
      refetch();
      queryClient.invalidateQueries({ queryKey: ["ml_project", mlProjectUuid] });
    },
    onError: () => {
      toast.error("Failed to delete model");
    },
  });

  const handleDelete = useCallback(
    (modelUuid: string) => {
      if (confirm("Are you sure you want to delete this model?")) {
        deleteMutation.mutate(modelUuid);
      }
    },
    [deleteMutation]
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
            Custom Models
          </h2>
          <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
            Train custom detection models using labeled search results
          </p>
        </div>
        <Button variant="primary" onClick={() => setShowCreateDialog(true)}>
          <Plus className="w-4 h-4 mr-2" />
          New Model
        </Button>
      </div>

      {/* Models List */}
      {models.length === 0 ? (
        <Empty>
          <Cpu className="w-12 h-12 mb-4 text-stone-400" />
          <p className="text-lg font-medium">No custom models</p>
          <p className="text-sm text-stone-500 mt-1">
            Create a model to train on your labeled search results
          </p>
          <Button
            variant="primary"
            className="mt-4"
            onClick={() => setShowCreateDialog(true)}
          >
            <Plus className="w-4 h-4 mr-2" />
            Create Model
          </Button>
        </Empty>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {models.map((model) => (
            <ModelCard
              key={model.uuid}
              model={model}
              mlProjectUuid={mlProjectUuid}
              onTrain={() => trainMutation.mutate(model.uuid)}
              onDeploy={() => deployMutation.mutate(model.uuid)}
              onArchive={() => archiveMutation.mutate(model.uuid)}
              onDelete={() => handleDelete(model.uuid)}
            />
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <CreateModelDialog
        isOpen={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        mlProjectUuid={mlProjectUuid}
        onSuccess={handleSuccess}
      />
    </div>
  );
}
