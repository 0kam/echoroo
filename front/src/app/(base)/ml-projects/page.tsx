"use client";

/**
 * ML Projects list page.
 *
 * Displays a paginated list of ML projects. Allows creating new ML projects
 * and navigating to individual project details.
 */
import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Plus,
  Bot,
  Database,
  Search,
  Cpu,
  Play,
  CheckCircle,
  Archive,
  Clock,
  Tags,
} from "lucide-react";

import api from "@/app/api";
import MLProjectCreateComponent from "@/app/components/ml_projects/MLProjectCreate";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Hero from "@/lib/components/ui/Hero";
import Loading from "@/lib/components/ui/Loading";
import Empty from "@/lib/components/ui/Empty";
import { DialogOverlay } from "@/lib/components/ui/Dialog";
import usePagedQuery from "@/lib/hooks/utils/usePagedQuery";

import type { MLProject, MLProjectStatus, MLProjectCreate } from "@/lib/types";

// Status badge colors - matches backend MLProjectStatus enum
const STATUS_COLORS: Record<MLProjectStatus, string> = {
  setup: "bg-stone-200 text-stone-700 dark:bg-stone-700 dark:text-stone-300",
  searching: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  labeling: "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300",
  training: "bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300",
  inference: "bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300",
  review: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300",
  completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
  archived: "bg-stone-300 text-stone-600 dark:bg-stone-600 dark:text-stone-400",
};

const STATUS_ICONS: Record<MLProjectStatus, React.ReactNode> = {
  setup: <Clock className="w-4 h-4" />,
  searching: <Search className="w-4 h-4" />,
  labeling: <Clock className="w-4 h-4" />,
  training: <Cpu className="w-4 h-4" />,
  inference: <Play className="w-4 h-4" />,
  review: <Clock className="w-4 h-4" />,
  completed: <CheckCircle className="w-4 h-4" />,
  archived: <Archive className="w-4 h-4" />,
};

function StatusBadge({ status }: { status: MLProjectStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-full ${STATUS_COLORS[status]}`}
    >
      {STATUS_ICONS[status]}
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function MLProjectCard({
  project,
  onClick,
}: {
  project: MLProject;
  onClick: () => void;
}) {
  return (
    <Card
      className="hover:border-emerald-500 dark:hover:border-emerald-500 cursor-pointer transition-colors"
      onClick={onClick}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
            {project.name}
          </h3>
          <p className="text-sm text-stone-500 dark:text-stone-400 mt-1 line-clamp-2">
            {project.description || "No description"}
          </p>
        </div>
        <StatusBadge status={project.status} />
      </div>

      <div className="flex items-center gap-4 mt-4 text-sm text-stone-600 dark:text-stone-400">
        {project.dataset_scope_count !== undefined && project.dataset_scope_count > 0 && (
          <div className="flex items-center gap-1">
            <Database className="w-4 h-4" />
            <span>{project.dataset_scope_count} datasets</span>
          </div>
        )}
        {project.target_tags && project.target_tags.length > 0 && (
          <div className="flex items-center gap-1">
            <Tags className="w-4 h-4" />
            <span>{project.target_tags.length} tags</span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 mt-2 text-xs text-stone-500 dark:text-stone-500">
        {project.reference_sound_count !== undefined && (
          <span>{project.reference_sound_count} reference sounds</span>
        )}
        {project.search_session_count !== undefined && (
          <span>{project.search_session_count} search sessions</span>
        )}
        {project.custom_model_count !== undefined && (
          <span>{project.custom_model_count} models</span>
        )}
      </div>
    </Card>
  );
}

function CreateMLProjectDialog({
  isOpen,
  onClose,
  onCreate,
}: {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (data: MLProjectCreate) => void;
}) {
  const handleCreate = useCallback(
    (data: MLProjectCreate) => {
      onCreate(data);
      onClose();
    },
    [onCreate, onClose],
  );

  return (
    <DialogOverlay
      title="Create ML Project"
      isOpen={isOpen}
      onClose={onClose}
    >
      <div className="w-[400px]">
        <MLProjectCreateComponent onCreateMLProject={handleCreate} />
      </div>
    </DialogOverlay>
  );
}

export default function MLProjectsPage() {
  const router = useRouter();
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);

  const { items, total, pagination, query } = usePagedQuery<MLProject, {}>({
    name: "ml_projects",
    queryFn: api.mlProjects.getMany,
    pageSize: 12,
    filter: {},
  });

  const handleProjectClick = useCallback(
    (project: MLProject) => {
      router.push(`/ml-projects/${project.uuid}`);
    },
    [router],
  );

  const handleCreateProject = useCallback(
    async (data: MLProjectCreate) => {
      try {
        const project = await api.mlProjects.create(data);
        query.refetch();
        router.push(`/ml-projects/${project.uuid}`);
      } catch (error) {
        console.error("Failed to create ML project:", error);
      }
    },
    [query, router],
  );

  return (
    <>
      <Hero text="ML Projects" />
      <div className="container mx-auto p-8">
        {/* Actions */}
        <div className="flex items-center justify-end mb-6">
          <Button
            variant="primary"
            onClick={() => setIsCreateDialogOpen(true)}
          >
            <Plus className="w-4 h-4 mr-2" />
            New ML Project
          </Button>
        </div>

        {/* Results */}
        {query.isLoading ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty>
            <Bot className="w-12 h-12 mb-4 text-stone-400" />
            <p className="text-lg font-medium">No ML projects found</p>
            <p className="text-sm text-stone-500 mt-1">
              Create your first ML project to start training custom sound detection models.
            </p>
            <Button
              variant="primary"
              className="mt-4"
              onClick={() => setIsCreateDialogOpen(true)}
            >
              <Plus className="w-4 h-4 mr-2" />
              Create ML Project
            </Button>
          </Empty>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {items.map((project) => (
                <MLProjectCard
                  key={project.uuid}
                  project={project}
                  onClick={() => handleProjectClick(project)}
                />
              ))}
            </div>

            {/* Pagination */}
            {pagination.numPages > 1 && (
              <div className="flex items-center justify-between mt-6">
                <p className="text-sm text-stone-600 dark:text-stone-400">
                  Showing {items.length} of {total} projects
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    disabled={!pagination.hasPrevPage}
                    onClick={pagination.prevPage}
                  >
                    Previous
                  </Button>
                  <span className="text-sm text-stone-600 dark:text-stone-400">
                    Page {pagination.page + 1} of {pagination.numPages}
                  </span>
                  <Button
                    variant="secondary"
                    disabled={!pagination.hasNextPage}
                    onClick={pagination.nextPage}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <CreateMLProjectDialog
        isOpen={isCreateDialogOpen}
        onClose={() => setIsCreateDialogOpen(false)}
        onCreate={handleCreateProject}
      />
    </>
  );
}
