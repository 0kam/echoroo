import { useCallback, useMemo, useState } from "react";

import {
  ModelIcon,
  SearchIcon,
  ClipsIcon,
} from "@/lib/components/icons";
import { Input, Select, Slider, Group } from "@/lib/components/inputs";
import type { Option } from "@/lib/components/inputs/Select";
import SearchResultCard from "@/lib/components/search/SearchResultCard";
import * as ui from "@/lib/components/ui";

import type { Clip } from "@/lib/types";

/** Model options for similarity search */
export type ModelName = "birdnet" | "perch";

/** Search result with similarity score */
export interface SimilaritySearchResult {
  clip: Clip;
  score: number;
}

/** Props for the SimilaritySearch component */
export interface SimilaritySearchProps {
  /** Optional pre-selected query clip */
  queryClip?: Clip;
  /** Default model to use for similarity search */
  modelName?: ModelName;
  /** Callback when a result clip is selected */
  onSelectClip?: (clip: Clip) => void;
  /** Callback to perform the search - implement this to connect to your API */
  onSearch?: (params: {
    clipUuid: string;
    model: ModelName;
    threshold: number;
  }) => Promise<SimilaritySearchResult[]>;
  /** Callback when a clip should be played */
  onPlayClip?: (clip: Clip) => void;
}

/** Model options for the select dropdown */
const MODEL_OPTIONS: Option<ModelName>[] = [
  { id: "birdnet", label: "BirdNET", value: "birdnet" },
  { id: "perch", label: "Perch", value: "perch" },
];

/**
 * SimilaritySearch component allows users to search for similar audio clips.
 *
 * Features:
 * - Select a query clip by UUID or use a provided clip
 * - Choose between different embedding models (BirdNET, Perch)
 * - Set a similarity threshold
 * - View results in a grid layout with similarity scores
 */
export default function SimilaritySearch({
  queryClip,
  modelName = "birdnet",
  onSelectClip,
  onSearch,
  onPlayClip,
}: SimilaritySearchProps) {
  // State for search parameters
  const [clipUuid, setClipUuid] = useState<string>(queryClip?.uuid ?? "");
  const [selectedModel, setSelectedModel] = useState<ModelName>(modelName);
  const [threshold, setThreshold] = useState<number>(0.5);

  // State for search results and loading
  const [results, setResults] = useState<SimilaritySearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedResultIndex, setSelectedResultIndex] = useState<number | null>(null);

  // Update clipUuid when queryClip changes
  useMemo(() => {
    if (queryClip?.uuid) {
      setClipUuid(queryClip.uuid);
    }
  }, [queryClip?.uuid]);

  // Get the selected model option
  const selectedModelOption = useMemo(
    () => MODEL_OPTIONS.find((opt) => opt.value === selectedModel) ?? MODEL_OPTIONS[0],
    [selectedModel],
  );

  // Handle search execution
  const handleSearch = useCallback(async () => {
    if (!clipUuid.trim()) {
      setError("Please enter a clip UUID");
      return;
    }

    // Validate UUID format
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(clipUuid.trim())) {
      setError("Invalid UUID format");
      return;
    }

    setError(null);
    setIsSearching(true);
    setSelectedResultIndex(null);

    try {
      if (onSearch) {
        const searchResults = await onSearch({
          clipUuid: clipUuid.trim(),
          model: selectedModel,
          threshold,
        });
        setResults(searchResults);
      } else {
        // Demo mode: show empty results with a message
        setResults([]);
        setError("Search function not implemented. Connect onSearch prop to your API.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
      setResults([]);
    } finally {
      setIsSearching(false);
    }
  }, [clipUuid, selectedModel, threshold, onSearch]);

  // Handle result selection
  const handleResultClick = useCallback(
    (index: number, clip: Clip) => {
      setSelectedResultIndex(index);
      onSelectClip?.(clip);
    },
    [onSelectClip],
  );

  // Handle play button click
  const handlePlay = useCallback(
    (clip: Clip) => {
      onPlayClip?.(clip);
    },
    [onPlayClip],
  );

  // Format threshold as percentage
  const formatThreshold = useCallback((value: number) => `${(value * 100).toFixed(0)}%`, []);

  return (
    <div className="flex flex-col gap-6">
      {/* Search Form */}
      <ui.Card>
        <ui.H3>Similarity Search</ui.H3>

        <div className="flex flex-col gap-4">
          {/* Clip UUID Input */}
          <Group label="Query Clip UUID" name="clipUuid">
            <Input
              name="clipUuid"
              type="text"
              placeholder="Enter clip UUID..."
              value={clipUuid}
              onChange={(e) => setClipUuid(e.target.value)}
              disabled={isSearching}
            />
          </Group>

          {/* Model Selection */}
          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-stone-700 dark:text-stone-300">
              Embedding Model
            </label>
            <Select
              selected={selectedModelOption}
              onChange={(value) => setSelectedModel(value)}
              options={MODEL_OPTIONS}
            />
          </div>

          {/* Threshold Slider */}
          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-stone-700 dark:text-stone-300">
              Similarity Threshold
            </label>
            <Slider
              label="Threshold"
              minValue={0}
              maxValue={1}
              step={0.05}
              value={threshold}
              onChange={(value) => setThreshold(value as number)}
              formatter={formatThreshold}
            />
          </div>

          {/* Search Button */}
          <ui.Button
            mode="filled"
            variant="primary"
            onClick={handleSearch}
            disabled={isSearching || !clipUuid.trim()}
          >
            <SearchIcon className="w-5 h-5 mr-2" />
            {isSearching ? "Searching..." : "Search Similar Clips"}
          </ui.Button>

          {/* Error Display */}
          {error && (
            <div className="p-3 rounded-md bg-red-100 dark:bg-red-900/30 border border-red-300 dark:border-red-700 text-red-700 dark:text-red-300 text-sm">
              {error}
            </div>
          )}
        </div>
      </ui.Card>

      {/* Query Clip Display */}
      {queryClip && (
        <ui.Card>
          <div className="flex items-center gap-2">
            <ClipsIcon className="w-5 h-5 text-emerald-500" />
            <ui.H4>Query Clip</ui.H4>
          </div>
          <div className="text-sm text-stone-600 dark:text-stone-400">
            <p className="truncate" title={queryClip.recording.path}>
              {queryClip.recording.path}
            </p>
            <p>
              {queryClip.start_time.toFixed(2)}s - {queryClip.end_time.toFixed(2)}s
            </p>
          </div>
        </ui.Card>
      )}

      {/* Search Configuration Summary */}
      <div className="flex items-center gap-4 text-sm text-stone-500 dark:text-stone-400">
        <div className="flex items-center gap-1">
          <ModelIcon className="w-4 h-4" />
          <span>{selectedModelOption.label}</span>
        </div>
        <div>
          Threshold: {formatThreshold(threshold)}
        </div>
        {results.length > 0 && (
          <div>
            {results.length} result{results.length !== 1 ? "s" : ""}
          </div>
        )}
      </div>

      {/* Results Grid */}
      {isSearching ? (
        <ui.Loading text="Searching for similar clips..." />
      ) : results.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {results.map((result, index) => (
            <SearchResultCard
              key={result.clip.uuid}
              clip={result.clip}
              similarityScore={result.score}
              isSelected={selectedResultIndex === index}
              onClick={() => handleResultClick(index, result.clip)}
              onPlay={() => handlePlay(result.clip)}
            />
          ))}
        </div>
      ) : !error && clipUuid ? (
        <ui.Empty>
          <SearchIcon className="w-8 h-8 mb-2" />
          <p>No results yet. Click "Search Similar Clips" to find similar audio.</p>
        </ui.Empty>
      ) : (
        <ui.Empty>
          <ClipsIcon className="w-8 h-8 mb-2" />
          <p>Enter a clip UUID to search for similar clips.</p>
        </ui.Empty>
      )}
    </div>
  );
}
