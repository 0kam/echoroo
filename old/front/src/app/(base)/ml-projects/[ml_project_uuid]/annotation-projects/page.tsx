"use client";

/**
 * Annotation Projects page for ML Projects.
 *
 * Lists all annotation projects created from this ML project's search sessions
 * and provides navigation to those projects.
 */
import { useCallback, useContext, useState, useMemo } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FolderOpen,
  Calendar,
  FileStack,
  ExternalLink,
  Search,
  Upload,
} from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import Link from "@/lib/components/ui/Link";

import ExportToAnnotationProjectDialog from "@/app/components/ml_projects/ExportToAnnotationProjectDialog";

import type { MLProjectAnnotationProject, SearchSession, SearchProgress } from "@/lib/types";

import MLProjectContext from "../context";

function AnnotationProjectCard({
  project,
}: {
  project: MLProjectAnnotationProject;
}) {
  const formattedDate = useMemo(() => {
    return new Date(project.created_on).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }, [project.created_on]);

  return (
    <Card className="hover:border-emerald-500/50 transition-colors">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <Link href={`/annotation-projects/${project.uuid}/`}>
            <h3 className="text-lg font-semibold text-stone-900 dark:text-stone-100 hover:text-emerald-600 dark:hover:text-emerald-400 flex items-center gap-2">
              <FolderOpen className="w-5 h-5" />
              {project.name}
            </h3>
          </Link>
          {project.description && (
            <p className="text-sm text-stone-500 dark:text-stone-400 mt-1 line-clamp-2">
              {project.description}
            </p>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="flex items-center gap-4 mt-4 text-sm text-stone-600 dark:text-stone-400">
        <div className="flex items-center gap-1">
          <FileStack className="w-4 h-4" />
          <span>{project.clip_count} clips</span>
        </div>
        <div className="flex items-center gap-1">
          <Calendar className="w-4 h-4" />
          <span>{formattedDate}</span>
        </div>
      </div>

      {/* Source Session Info */}
      {project.source_search_session_uuid && (
        <div className="mt-3 pt-3 border-t border-stone-200 dark:border-stone-700 text-xs text-stone-500 dark:text-stone-400">
          <span>Created from search session</span>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-end mt-4 pt-3 border-t border-stone-200 dark:border-stone-700">
        <Link href={`/annotation-projects/${project.uuid}/`}>
          <Button variant="primary" mode="text">
            Open Project
            <ExternalLink className="w-4 h-4 ml-1" />
          </Button>
        </Link>
      </div>
    </Card>
  );
}

export default function AnnotationProjectsPage() {
  const params = useParams();
  const mlProjectUuid = params.ml_project_uuid as string;
  const mlProject = useContext(MLProjectContext);
  const queryClient = useQueryClient();

  // State for export dialog
  const [showExportDialog, setShowExportDialog] = useState(false);
  const [selectedSession, setSelectedSession] = useState<SearchSession | null>(null);
  const [sessionProgress, setSessionProgress] = useState<SearchProgress | null>(null);

  // Fetch annotation projects for this ML project
  const { data: annotationProjects, isLoading: projectsLoading, refetch } = useQuery({
    queryKey: ["ml_project_annotation_projects", mlProjectUuid],
    queryFn: () => api.mlProjects.annotationProjects.list(mlProjectUuid),
    enabled: !!mlProjectUuid,
  });

  // Fetch search sessions for export dialog
  const { data: sessionsData, isLoading: sessionsLoading } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_sessions"],
    queryFn: () => api.searchSessions.getMany(mlProjectUuid, { limit: 100 }),
    enabled: !!mlProjectUuid,
  });

  // Completed sessions only
  const completedSessions = useMemo(() => {
    return (sessionsData?.items || []).filter((s) => s.is_search_complete);
  }, [sessionsData]);

  // Handle export button click
  const handleExportClick = useCallback(async () => {
    if (completedSessions.length === 0) {
      return;
    }
    // Select the first session and fetch its progress
    const session = completedSessions[0];
    setSelectedSession(session);
    try {
      const progress = await api.searchSessions.getProgress(mlProjectUuid, session.uuid);
      setSessionProgress(progress);
      setShowExportDialog(true);
    } catch (error) {
      console.error("Failed to fetch session progress:", error);
    }
  }, [completedSessions, mlProjectUuid]);

  // Handle session change in export dialog
  const handleSessionChange = useCallback(async (session: SearchSession) => {
    setSelectedSession(session);
    try {
      const progress = await api.searchSessions.getProgress(mlProjectUuid, session.uuid);
      setSessionProgress(progress);
    } catch (error) {
      console.error("Failed to fetch session progress:", error);
    }
  }, [mlProjectUuid]);

  if (projectsLoading || sessionsLoading) {
    return <Loading />;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-stone-900 dark:text-stone-100">
            Annotation Projects
          </h2>
          <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
            Annotation projects created from this ML project&apos;s curated results
          </p>
        </div>
        {completedSessions.length > 0 && (
          <Button
            variant="primary"
            onClick={handleExportClick}
          >
            <Upload className="w-4 h-4 mr-2" />
            Export to Annotation Project
          </Button>
        )}
      </div>

      {/* Projects List */}
      {!annotationProjects || annotationProjects.length === 0 ? (
        <Empty>
          <FolderOpen className="w-12 h-12 mb-4 text-stone-400" />
          <p className="text-lg font-medium">No annotation projects yet</p>
          <p className="text-sm text-stone-500 mt-1">
            Export curated results from search sessions to create annotation projects
          </p>
          {completedSessions.length > 0 ? (
            <Button
              variant="primary"
              className="mt-4"
              onClick={handleExportClick}
            >
              <Upload className="w-4 h-4 mr-2" />
              Export to Annotation Project
            </Button>
          ) : (
            <p className="text-xs text-stone-400 mt-4">
              Complete a search session first to enable export.
            </p>
          )}
        </Empty>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {annotationProjects.map((project) => (
            <AnnotationProjectCard
              key={project.uuid}
              project={project}
            />
          ))}
        </div>
      )}

      {/* Export Dialog */}
      {selectedSession && sessionProgress && (
        <ExportToAnnotationProjectDialog
          isOpen={showExportDialog}
          onClose={() => {
            setShowExportDialog(false);
            refetch();
          }}
          mlProjectUuid={mlProjectUuid}
          searchSession={selectedSession}
          progress={sessionProgress}
        />
      )}

      {/* Session Selector for Export */}
      {showExportDialog && completedSessions.length > 1 && (
        <div className="fixed bottom-4 left-1/2 transform -translate-x-1/2 bg-white dark:bg-stone-800 shadow-lg rounded-lg p-4 border border-stone-200 dark:border-stone-700">
          <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-2">
            Select Search Session:
          </label>
          <select
            value={selectedSession?.uuid || ""}
            onChange={(e) => {
              const session = completedSessions.find((s) => s.uuid === e.target.value);
              if (session) handleSessionChange(session);
            }}
            className="w-64 px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
          >
            {completedSessions.map((session) => (
              <option key={session.uuid} value={session.uuid}>
                {session.name}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
