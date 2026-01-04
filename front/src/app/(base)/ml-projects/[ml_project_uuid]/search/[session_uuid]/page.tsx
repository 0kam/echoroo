"use client";

/**
 * Search Session detail / Labeling interface page.
 *
 * Displays search results with spectrograms and provides
 * labeling functionality with keyboard shortcuts.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  Play,
  CheckCircle,
  XCircle,
  HelpCircle,
  SkipForward,
  ArrowLeft,
  ArrowRight,
  Loader2,
  Tag,
  Music,
  Filter,
  ChevronLeft,
  Check,
} from "lucide-react";

import api from "@/app/api";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import ProgressBar from "@/lib/components/ui/ProgressBar";
import Link from "@/lib/components/ui/Link";

import type { SearchSession, SearchResult, SearchResultLabel, SearchProgress } from "@/lib/types";

// Label colors
const LABEL_COLORS: Record<SearchResultLabel, string> = {
  unlabeled: "bg-stone-100 text-stone-600 dark:bg-stone-700 dark:text-stone-400",
  positive: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  negative: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  uncertain: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
  skipped: "bg-stone-200 text-stone-500 dark:bg-stone-600 dark:text-stone-400",
  positive_reference: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  negative_reference: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
};

const LABEL_ICONS: Record<SearchResultLabel, React.ReactNode> = {
  unlabeled: null,
  positive: <CheckCircle className="w-4 h-4" />,
  negative: <XCircle className="w-4 h-4" />,
  uncertain: <HelpCircle className="w-4 h-4" />,
  skipped: <SkipForward className="w-4 h-4" />,
  positive_reference: <CheckCircle className="w-4 h-4" />,
  negative_reference: <XCircle className="w-4 h-4" />,
};

function LabelButton({
  label,
  shortcut,
  onClick,
  active,
  disabled,
}: {
  label: string;
  shortcut: string;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  const colors: Record<string, string> = {
    Positive: "hover:bg-emerald-100 dark:hover:bg-emerald-900/30 hover:text-emerald-700 dark:hover:text-emerald-400",
    Negative: "hover:bg-red-100 dark:hover:bg-red-900/30 hover:text-red-700 dark:hover:text-red-400",
    Uncertain: "hover:bg-yellow-100 dark:hover:bg-yellow-900/30 hover:text-yellow-700 dark:hover:text-yellow-400",
    Skip: "hover:bg-stone-200 dark:hover:bg-stone-600 hover:text-stone-600 dark:hover:text-stone-300",
  };

  const activeColors: Record<string, string> = {
    Positive: "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 ring-2 ring-emerald-500",
    Negative: "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 ring-2 ring-red-500",
    Uncertain: "bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 ring-2 ring-yellow-500",
    Skip: "bg-stone-200 dark:bg-stone-600 text-stone-600 dark:text-stone-300 ring-2 ring-stone-500",
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
        active ? activeColors[label] : colors[label]
      } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
    >
      <span className="font-medium">{label}</span>
      <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">
        {shortcut}
      </kbd>
    </button>
  );
}

function ResultCard({
  result,
  isSelected,
  onClick,
}: {
  result: SearchResult;
  isSelected: boolean;
  onClick: () => void;
}) {
  return (
    <Card
      className={`cursor-pointer transition-all ${
        isSelected
          ? "ring-2 ring-emerald-500 border-emerald-500"
          : "hover:border-emerald-500/50"
      }`}
      onClick={onClick}
    >
      {/* Spectrogram placeholder */}
      <div className="aspect-[2/1] bg-stone-100 dark:bg-stone-800 rounded-lg mb-2 flex items-center justify-center relative">
        <Music className="w-8 h-8 text-stone-400" />
        {/* Similarity badge */}
        <span className="absolute top-2 right-2 px-2 py-0.5 text-xs bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 rounded-full">
          {(result.similarity * 100).toFixed(1)}%
        </span>
      </div>

      {/* Label badge */}
      <div className="flex items-center justify-between">
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${LABEL_COLORS[result.label]}`}
        >
          {LABEL_ICONS[result.label]}
          {result.label.charAt(0).toUpperCase() + result.label.slice(1)}
        </span>
        <span className="text-xs text-stone-500">#{result.rank}</span>
      </div>
    </Card>
  );
}

function KeyboardShortcutsHelp() {
  return (
    <Card className="p-4">
      <h4 className="font-medium text-sm mb-2">Keyboard Shortcuts</h4>
      <div className="space-y-1 text-sm text-stone-600 dark:text-stone-400">
        <div className="flex justify-between">
          <span>Positive</span>
          <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">P</kbd>
        </div>
        <div className="flex justify-between">
          <span>Negative</span>
          <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">N</kbd>
        </div>
        <div className="flex justify-between">
          <span>Uncertain</span>
          <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">U</kbd>
        </div>
        <div className="flex justify-between">
          <span>Skip</span>
          <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">S</kbd>
        </div>
        <div className="flex justify-between">
          <span>Previous</span>
          <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">Left Arrow</kbd>
        </div>
        <div className="flex justify-between">
          <span>Next</span>
          <kbd className="px-1.5 py-0.5 text-xs bg-stone-200 dark:bg-stone-700 rounded">Right Arrow</kbd>
        </div>
      </div>
    </Card>
  );
}

export default function SearchSessionDetailPage() {
  const params = useParams();
  const router = useRouter();
  const mlProjectUuid = params.ml_project_uuid as string;
  const sessionUuid = params.session_uuid as string;
  const queryClient = useQueryClient();

  const [selectedIndex, setSelectedIndex] = useState(0);
  const [labelFilter, setLabelFilter] = useState<SearchResultLabel | "all">("all");
  const [page, setPage] = useState(0);
  const pageSize = 24;

  // Fetch session
  const { data: session, isLoading: sessionLoading, refetch: refetchSession } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_session", sessionUuid],
    queryFn: () => api.searchSessions.get(mlProjectUuid, sessionUuid),
    enabled: !!mlProjectUuid && !!sessionUuid,
  });

  // Fetch results
  const { data: resultsData, isLoading: resultsLoading, refetch: refetchResults } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_session", sessionUuid, "results", labelFilter, page],
    queryFn: () =>
      api.searchSessions.getResults(mlProjectUuid, sessionUuid, {
        limit: pageSize,
        offset: page * pageSize,
        label: labelFilter === "all" ? undefined : labelFilter,
      }),
    enabled: !!session?.is_search_complete,
  });

  // Fetch progress
  const { data: progress, refetch: refetchProgress } = useQuery({
    queryKey: ["ml_project", mlProjectUuid, "search_session", sessionUuid, "progress"],
    queryFn: () => api.searchSessions.getProgress(mlProjectUuid, sessionUuid),
    enabled: !!session?.is_search_complete,
    refetchInterval: session?.is_labeling_complete ? false : 5000,
  });

  const results = resultsData?.items || [];
  const totalResults = resultsData?.total || 0;
  const numPages = Math.ceil(totalResults / pageSize);

  const selectedResult = results[selectedIndex];

  // Execute search mutation
  const executeMutation = useMutation({
    mutationFn: () => api.searchSessions.execute(mlProjectUuid, sessionUuid),
    onSuccess: () => {
      toast.success("Search started");
      refetchSession();
    },
    onError: () => {
      toast.error("Failed to execute search");
    },
  });

  // Label result mutation
  const labelMutation = useMutation({
    mutationFn: ({ resultUuid, label }: { resultUuid: string; label: SearchResultLabel }) =>
      api.searchSessions.labelResult(mlProjectUuid, sessionUuid, resultUuid, { label }),
    onSuccess: () => {
      refetchResults();
      refetchProgress();
      // Move to next result
      if (selectedIndex < results.length - 1) {
        setSelectedIndex(selectedIndex + 1);
      } else if (page < numPages - 1) {
        setPage(page + 1);
        setSelectedIndex(0);
      }
    },
    onError: () => {
      toast.error("Failed to label result");
    },
  });

  // Mark complete mutation
  const markCompleteMutation = useMutation({
    mutationFn: () => api.searchSessions.markComplete(mlProjectUuid, sessionUuid),
    onSuccess: () => {
      toast.success("Session marked as complete");
      refetchSession();
      queryClient.invalidateQueries({ queryKey: ["ml_project", mlProjectUuid] });
    },
    onError: () => {
      toast.error("Failed to mark session as complete");
    },
  });

  // Handle label
  const handleLabel = useCallback(
    (label: SearchResultLabel) => {
      if (!selectedResult || labelMutation.isPending) return;
      labelMutation.mutate({ resultUuid: selectedResult.uuid, label });
    },
    [selectedResult, labelMutation],
  );

  // Handle navigation
  const handlePrevious = useCallback(() => {
    if (selectedIndex > 0) {
      setSelectedIndex(selectedIndex - 1);
    } else if (page > 0) {
      setPage(page - 1);
      setSelectedIndex(pageSize - 1);
    }
  }, [selectedIndex, page, pageSize]);

  const handleNext = useCallback(() => {
    if (selectedIndex < results.length - 1) {
      setSelectedIndex(selectedIndex + 1);
    } else if (page < numPages - 1) {
      setPage(page + 1);
      setSelectedIndex(0);
    }
  }, [selectedIndex, results.length, page, numPages]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

      switch (e.key.toLowerCase()) {
        case "p":
          handleLabel("positive");
          break;
        case "n":
          handleLabel("negative");
          break;
        case "u":
          handleLabel("uncertain");
          break;
        case "s":
          handleLabel("skipped");
          break;
        case "arrowleft":
          handlePrevious();
          break;
        case "arrowright":
          handleNext();
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleLabel, handlePrevious, handleNext]);

  if (sessionLoading) {
    return <Loading />;
  }

  if (!session) {
    return null;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href={`/ml-projects/${mlProjectUuid}/search`}>
            <Button variant="secondary" mode="text">
              <ChevronLeft className="w-4 h-4 mr-1" />
              Back to Sessions
            </Button>
          </Link>
          <div>
            <h2 className="text-xl font-semibold text-stone-900 dark:text-stone-100">
              {session.name}
            </h2>
            <div className="flex items-center gap-2 mt-1 text-sm text-stone-500 dark:text-stone-400">
              <Tag className="w-4 h-4" />
              <span>{session.target_tag.key}: {session.target_tag.value}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {session.is_search_complete && !session.is_labeling_complete && (
            <Button
              variant="primary"
              onClick={() => markCompleteMutation.mutate()}
              disabled={markCompleteMutation.isPending}
            >
              {markCompleteMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Check className="w-4 h-4 mr-2" />
              )}
              Mark Complete
            </Button>
          )}
        </div>
      </div>

      {/* Not executed yet */}
      {!session.is_search_complete && (
        <Card className="p-8 text-center">
          <Play className="w-12 h-12 mx-auto mb-4 text-stone-400" />
          <h3 className="text-lg font-medium">Search Not Executed</h3>
          <p className="text-sm text-stone-500 dark:text-stone-400 mt-2 mb-4">
            Execute the search to find similar sounds in the dataset based on your reference sounds.
          </p>
          <Button
            variant="primary"
            onClick={() => executeMutation.mutate()}
            disabled={executeMutation.isPending}
          >
            {executeMutation.isPending ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Executing...
              </>
            ) : (
              <>
                <Play className="w-4 h-4 mr-2" />
                Execute Search
              </>
            )}
          </Button>
        </Card>
      )}

      {/* Search executed - show results */}
      {session.is_search_complete && (
        <>
          {/* Progress */}
          {progress && (
            <Card className="p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium">Labeling Progress</span>
                <span className="text-sm text-stone-500">
                  {progress.labeled} / {progress.total} labeled
                </span>
              </div>
              <ProgressBar
                total={progress.total}
                complete={progress.positive + progress.negative}
                verified={progress.uncertain}
                error={progress.skipped}
                className="mb-2"
              />
              <div className="flex items-center gap-4 text-xs text-stone-500">
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full bg-emerald-500" />
                  Positive: {progress.positive}
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full bg-red-500" />
                  Negative: {progress.negative}
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full bg-amber-500" />
                  Uncertain: {progress.uncertain}
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full bg-blue-500" />
                  Unlabeled: {progress.unlabeled}
                </span>
              </div>
            </Card>
          )}

          {/* Filter */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-stone-400" />
              <span className="text-sm text-stone-600 dark:text-stone-400">Filter:</span>
            </div>
            <select
              value={labelFilter}
              onChange={(e) => {
                setLabelFilter(e.target.value as SearchResultLabel | "all");
                setPage(0);
                setSelectedIndex(0);
              }}
              className="px-3 py-1.5 text-sm border border-stone-300 dark:border-stone-600 rounded-lg bg-white dark:bg-stone-800 text-stone-900 dark:text-stone-100"
            >
              <option value="all">All labels</option>
              <option value="unlabeled">Unlabeled</option>
              <option value="positive">Positive</option>
              <option value="negative">Negative</option>
              <option value="uncertain">Uncertain</option>
              <option value="skipped">Skipped</option>
            </select>
            <span className="text-sm text-stone-500">
              {totalResults} results
            </span>
          </div>

          {/* Main content */}
          <div className="grid grid-cols-12 gap-6">
            {/* Results grid */}
            <div className="col-span-8">
              {resultsLoading ? (
                <Loading />
              ) : results.length === 0 ? (
                <Empty>
                  <Music className="w-12 h-12 mb-4 text-stone-400" />
                  <p className="text-lg font-medium">No results found</p>
                  <p className="text-sm text-stone-500 mt-1">
                    {labelFilter !== "all"
                      ? "Try changing the filter to see more results"
                      : "The search did not return any results"}
                  </p>
                </Empty>
              ) : (
                <>
                  <div className="grid grid-cols-4 gap-3">
                    {results.map((result, index) => (
                      <ResultCard
                        key={result.uuid}
                        result={result}
                        isSelected={index === selectedIndex}
                        onClick={() => setSelectedIndex(index)}
                      />
                    ))}
                  </div>

                  {/* Pagination */}
                  {numPages > 1 && (
                    <div className="flex items-center justify-between mt-4">
                      <Button
                        variant="secondary"
                        disabled={page === 0}
                        onClick={() => {
                          setPage(page - 1);
                          setSelectedIndex(0);
                        }}
                      >
                        <ArrowLeft className="w-4 h-4 mr-1" />
                        Previous
                      </Button>
                      <span className="text-sm text-stone-500">
                        Page {page + 1} of {numPages}
                      </span>
                      <Button
                        variant="secondary"
                        disabled={page >= numPages - 1}
                        onClick={() => {
                          setPage(page + 1);
                          setSelectedIndex(0);
                        }}
                      >
                        Next
                        <ArrowRight className="w-4 h-4 ml-1" />
                      </Button>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Labeling panel */}
            <div className="col-span-4 space-y-4">
              {selectedResult && (
                <Card className="p-4">
                  <h4 className="font-medium mb-4">
                    Result #{selectedResult.rank}
                    <span className="ml-2 text-sm font-normal text-stone-500">
                      Similarity: {(selectedResult.similarity * 100).toFixed(1)}%
                    </span>
                  </h4>

                  {/* Spectrogram placeholder */}
                  <div className="aspect-[2/1] bg-stone-100 dark:bg-stone-800 rounded-lg mb-4 flex items-center justify-center">
                    <Music className="w-12 h-12 text-stone-400" />
                  </div>

                  {/* Current label */}
                  <div className="mb-4">
                    <span className="text-sm text-stone-500">Current label:</span>
                    <span
                      className={`ml-2 inline-flex items-center gap-1 px-2 py-0.5 text-sm font-medium rounded-full ${LABEL_COLORS[selectedResult.label]}`}
                    >
                      {LABEL_ICONS[selectedResult.label]}
                      {selectedResult.label.charAt(0).toUpperCase() + selectedResult.label.slice(1)}
                    </span>
                  </div>

                  {/* Label buttons */}
                  <div className="grid grid-cols-2 gap-2">
                    <LabelButton
                      label="Positive"
                      shortcut="P"
                      onClick={() => handleLabel("positive")}
                      active={selectedResult.label === "positive"}
                      disabled={labelMutation.isPending}
                    />
                    <LabelButton
                      label="Negative"
                      shortcut="N"
                      onClick={() => handleLabel("negative")}
                      active={selectedResult.label === "negative"}
                      disabled={labelMutation.isPending}
                    />
                    <LabelButton
                      label="Uncertain"
                      shortcut="U"
                      onClick={() => handleLabel("uncertain")}
                      active={selectedResult.label === "uncertain"}
                      disabled={labelMutation.isPending}
                    />
                    <LabelButton
                      label="Skip"
                      shortcut="S"
                      onClick={() => handleLabel("skipped")}
                      active={selectedResult.label === "skipped"}
                      disabled={labelMutation.isPending}
                    />
                  </div>

                  {/* Navigation */}
                  <div className="flex items-center justify-between mt-4 pt-4 border-t border-stone-200 dark:border-stone-700">
                    <Button
                      variant="secondary"
                      mode="text"
                      onClick={handlePrevious}
                      disabled={selectedIndex === 0 && page === 0}
                    >
                      <ArrowLeft className="w-4 h-4 mr-1" />
                      Previous
                    </Button>
                    <Button
                      variant="secondary"
                      mode="text"
                      onClick={handleNext}
                      disabled={selectedIndex >= results.length - 1 && page >= numPages - 1}
                    >
                      Next
                      <ArrowRight className="w-4 h-4 ml-1" />
                    </Button>
                  </div>
                </Card>
              )}

              {/* Keyboard shortcuts help */}
              <KeyboardShortcutsHelp />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
