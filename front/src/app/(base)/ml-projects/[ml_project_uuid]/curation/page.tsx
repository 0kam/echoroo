"use client";

/**
 * Curation page for ML Projects.
 *
 * Allows users to curate search results by labeling them with various labels
 * including positive/negative references for training data selection.
 */
import { useCallback, useContext, useState, useMemo } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  Tag as TagIcon,
  BarChart2,
  Upload,
  Search,
} from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import { DialogOverlay } from "@/lib/components/ui/Dialog";

import CurationGrid from "@/app/components/ml_projects/CurationGrid";
import ExportToAnnotationProjectDialog from "@/app/components/ml_projects/ExportToAnnotationProjectDialog";

import type { SearchSession, SearchProgress, CurationLabel } from "@/lib/types";

import MLProjectContext from "../context";

// Label statistics display configuration
const LABEL_STATS_CONFIG: Record<string, { label: string; color: string }> = {
  positive: { label: "Positive", color: "text-emerald-600 dark:text-emerald-400" },
  negative: { label: "Negative", color: "text-rose-600 dark:text-rose-400" },
  uncertain: { label: "Uncertain", color: "text-amber-600 dark:text-amber-400" },
  skipped: { label: "Skipped", color: "text-stone-500 dark:text-stone-400" },
  positive_reference: { label: "+ Ref", color: "text-blue-600 dark:text-blue-400" },
  negative_reference: { label: "- Ref", color: "text-purple-600 dark:text-purple-400" },
  unlabeled: { label: "Unlabeled", color: "text-stone-400 dark:text-stone-500" },
};

function SessionSelector({
  sessions,
  selectedSession,
  onSelect,
}: {
  sessions: SearchSession[];
  selectedSession: SearchSession | null;
  onSelect: (session: SearchSession) => void;
}) {
  if (sessions.length === 0) {
    return null;
  }

  return (
    <div>
      <label className="block text-sm font-medium text-stone-700 dark:text-stone-300 mb-1">
        Search Session
      </label>
      <select
        value={selectedSession?.uuid || ""}
        onChange={(e) => {
          const session = sessions.find((s) => s.uuid === e.target.value);
          if (session) onSelect(session);
        }}
        className="w-full px-3 py-2 border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100 focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none"
      >
        <option value="">Select a session...</option>
        {sessions.map((session) => (
          <option key={session.uuid} value={session.uuid}>
            {session.name} ({session.result_count} results)
          </option>
        ))}
      </select>
    </div>
  );
}

function StatsPanel({ progress }: { progress: SearchProgress | null }) {
  if (!progress) {
    return null;
  }

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <BarChart2 className="w-4 h-4 text-stone-500" />
        <h3 className="text-sm font-medium text-stone-700 dark:text-stone-300">
          Label Statistics
        </h3>
      </div>
      <div className="grid grid-cols-4 md:grid-cols-7 gap-3">
        {Object.entries(LABEL_STATS_CONFIG).map(([key, { label, color }]) => {
          const count = progress[key as keyof SearchProgress] ?? 0;
          return (
            <div key={key} className="text-center">
              <div className={`text-lg font-bold ${color}`}>
                {typeof count === "number" ? count : 0}
              </div>
              <div className="text-xs text-stone-500 dark:text-stone-400">
                {label}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 pt-3 border-t border-stone-200 dark:border-stone-700">
        <div className="flex justify-between text-sm">
          <span className="text-stone-500">Total Labeled:</span>
          <span className="font-medium text-stone-700 dark:text-stone-200">
            {progress.labeled} / {progress.total}
          </span>
        </div>
      </div>
    </Card>
  );
}

export default function CurationPage() {
  const params = useParams();
  const mlProjectUuid = params.ml_project_uuid as string;
  const mlProject = useContext(MLProjectContext);
  const queryClient = useQueryClient();

  // State
  const [selectedSession, setSelectedSession] = useState<SearchSession | null>(null);
  const [page, setPage] = useState(0);
  const [pageSize] = useState(24);
  const [selectedResults, setSelectedResults] = useState<Set<string>>(new Set());
  const [filterLabel, setFilterLabel] = useState<string>("all");
  const [similarityRange, setSimilarityRange] = useState<[number, number]>([0, 1]);
  const [showExportDialog, setShowExportDialog] = useState(false);

  // Fetch search sessions
  const { data: sessionsData, isLoading: sessionsLoading } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_sessions"],
    queryFn: () => api.searchSessions.getMany(mlProjectUuid, { limit: 100 }),
    enabled: !!mlProjectUuid,
  });

  // Completed sessions only for curation
  const completedSessions = useMemo(() => {
    return (sessionsData?.items || []).filter((s) => s.is_search_complete);
  }, [sessionsData]);

  // Select first session by default when loaded
  useMemo(() => {
    if (completedSessions.length > 0 && !selectedSession) {
      setSelectedSession(completedSessions[0]);
    }
  }, [completedSessions, selectedSession]);

  // Fetch progress for selected session
  const { data: progress, refetch: refetchProgress } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_session", selectedSession?.uuid, "progress"],
    queryFn: () =>
      api.searchSessions.getProgress(mlProjectUuid, selectedSession!.uuid),
    enabled: !!mlProjectUuid && !!selectedSession,
  });

  // Fetch results for selected session
  const { data: resultsData, isLoading: resultsLoading, refetch: refetchResults } = useQuery({
    queryKey: [
      "ml_project",
      mlProjectUuid,
      "search_session",
      selectedSession?.uuid,
      "results",
      page,
      pageSize,
      filterLabel,
    ],
    queryFn: () =>
      api.searchSessions.getResults(mlProjectUuid, selectedSession!.uuid, {
        limit: pageSize,
        offset: page * pageSize,
        label: filterLabel === "all" ? undefined : (filterLabel as any),
      }),
    enabled: !!mlProjectUuid && !!selectedSession,
  });

  const results = useMemo(() => resultsData?.items || [], [resultsData?.items]);
  const totalResults = resultsData?.total || 0;

  // Bulk curate mutation
  const curateMutation = useMutation({
    mutationFn: async ({
      uuids,
      label,
    }: {
      uuids: string[];
      label: CurationLabel;
    }) => {
      return api.searchSessions.bulkCurate(mlProjectUuid, selectedSession!.uuid, {
        result_uuids: uuids,
        label,
      });
    },
    onSuccess: (data) => {
      toast.success(`Updated ${data.updated_count} result(s)`);
      setSelectedResults(new Set());
      refetchResults();
      refetchProgress();
      queryClient.invalidateQueries({
        queryKey: ["ml_project", mlProjectUuid, "search_sessions"],
      });
    },
    onError: (error) => {
      toast.error(`Failed to update labels: ${error instanceof Error ? error.message : "Unknown error"}`);
    },
  });

  const { mutate: mutateCurate, isPending: isCurating } = curateMutation;

  // Handlers
  const handleSessionSelect = useCallback((session: SearchSession) => {
    setSelectedSession(session);
    setPage(0);
    setSelectedResults(new Set());
    setFilterLabel("all");
  }, []);

  const handleToggleSelect = useCallback((uuid: string) => {
    setSelectedResults((prev) => {
      const next = new Set(prev);
      if (next.has(uuid)) {
        next.delete(uuid);
      } else {
        next.add(uuid);
      }
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    setSelectedResults(new Set(results.map((r) => r.uuid)));
  }, [results]);

  const handleDeselectAll = useCallback(() => {
    setSelectedResults(new Set());
  }, []);

  const handleBulkLabel = useCallback(
    (label: CurationLabel) => {
      if (selectedResults.size === 0) {
        toast.error("No results selected");
        return;
      }
      mutateCurate({
        uuids: Array.from(selectedResults),
        label,
      });
    },
    [selectedResults, mutateCurate],
  );

  const handlePageChange = useCallback((newPage: number) => {
    setPage(newPage);
    setSelectedResults(new Set());
  }, []);

  const handleFilterChange = useCallback((label: string) => {
    setFilterLabel(label);
    setPage(0);
    setSelectedResults(new Set());
  }, []);

  if (sessionsLoading) {
    return <Loading />;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-stone-900 dark:text-stone-100">
            Curation
          </h2>
          <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
            Review and label search results, select training references
          </p>
        </div>
        {selectedSession && (
          <Button
            variant="primary"
            onClick={() => setShowExportDialog(true)}
          >
            <Upload className="w-4 h-4 mr-2" />
            Export to Annotation Project
          </Button>
        )}
      </div>

      {/* Session Selector */}
      {completedSessions.length === 0 ? (
        <Empty>
          <Search className="w-12 h-12 mb-4 text-stone-400" />
          <p className="text-lg font-medium">No completed search sessions</p>
          <p className="text-sm text-stone-500 mt-1">
            Complete a search session first to start curating results
          </p>
        </Empty>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="md:col-span-1">
              <SessionSelector
                sessions={completedSessions}
                selectedSession={selectedSession}
                onSelect={handleSessionSelect}
              />
            </div>
            <div className="md:col-span-2">
              <StatsPanel progress={progress || null} />
            </div>
          </div>

          {/* Results Grid */}
          {selectedSession && (
            <div>
              {resultsLoading ? (
                <Loading />
              ) : results.length === 0 && filterLabel === "all" ? (
                <Card className="p-8 text-center">
                  <p className="text-stone-500">No search results found for this session.</p>
                </Card>
              ) : (
                <CurationGrid
                  results={results}
                  page={page}
                  pageSize={pageSize}
                  totalResults={totalResults}
                  selectedResults={selectedResults}
                  isLabeling={isCurating}
                  onToggleSelect={handleToggleSelect}
                  onSelectAll={handleSelectAll}
                  onDeselectAll={handleDeselectAll}
                  onBulkLabel={handleBulkLabel}
                  onPageChange={handlePageChange}
                  filterLabel={filterLabel}
                  onFilterChange={handleFilterChange}
                  similarityRange={similarityRange}
                  onSimilarityRangeChange={setSimilarityRange}
                />
              )}
            </div>
          )}
        </>
      )}

      {/* Export Dialog */}
      {selectedSession && (
        <ExportToAnnotationProjectDialog
          isOpen={showExportDialog}
          onClose={() => setShowExportDialog(false)}
          mlProjectUuid={mlProjectUuid}
          searchSession={selectedSession}
          progress={progress || null}
        />
      )}
    </div>
  );
}
