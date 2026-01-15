import { useCallback, useMemo, useState } from "react";

import useSpeciesSearch from "@/app/hooks/api/useSpeciesSearch";
import useTags from "@/app/hooks/api/useTags";

import useStore from "@/app/store";

import TagSearchBarBase, {
  type TagSearchBarProps,
} from "@/lib/components/tags/TagSearchBar";

import type { Tag } from "@/lib/types";

/**
 * Species tag search powered by the GBIF Backbone taxonomy.
 *
 * Users type a scientific name, press the search button, and pick a match.
 * Once a match is selected the tag is created (or reused) on the backend and
 * passed to the provided callbacks.
 */
export default function TagSearchBar({
  onCreateTag,
  onSelectTag,
  limit = 10,
  enabled = true,
  ...props
}: TagSearchBarProps & { limit?: number; enabled?: boolean }) {
  const tagColorFn = useStore((state) => state.getTagColor);
  const { create } = useTags();

  const [inputQuery, setInputQuery] = useState("");
  const [searchState, setSearchState] = useState<{
    term: string;
    requestId: number;
  }>({
    term: "",
    requestId: 0,
  });
  const [validationMessage, setValidationMessage] = useState<string | null>(null);

  const shouldEnableSearch =
    enabled &&
    searchState.requestId > 0 &&
    searchState.term.trim().length >= 2;

  const {
    data: suggestions = [],
    isFetching,
  } = useSpeciesSearch({
    query: searchState.term,
    limit,
    enabled: shouldEnableSearch,
    requestId: searchState.requestId,
  });

  const tags = useMemo<Tag[]>(() => {
    return suggestions.map((candidate) => ({
      key: "species",
      value: candidate.usage_key,
      canonical_name: candidate.canonical_name,
      vernacular_name: candidate.vernacular_name ?? undefined,
    }));
  }, [suggestions]);

  const handleSelect = useCallback(
    async (tag: Tag) => {
      try {
        const created = await create.mutateAsync(tag);
        onCreateTag?.(created);
        onSelectTag?.(created);
      } catch (error) {
        // エラー処理はミューテーション側に委ねる
      }
    },
    [create, onCreateTag, onSelectTag],
  );

  const handleSearch = useCallback(() => {
    const trimmed = inputQuery.trim();
    if (trimmed.length < 2) {
      setValidationMessage("Please enter at least two characters.");
      setSearchState((prev) => ({ ...prev, term: trimmed }));
      return;
    }

    setValidationMessage(null);
    setSearchState((prev) => ({
      term: trimmed,
      requestId: prev.requestId + 1,
    }));
  }, [inputQuery]);

  const emptyMessage =
    validationMessage ??
    (searchState.requestId > 0 && !isFetching
      ? "No matching species were found."
      : "Enter a scientific name and press Search.");

  return (
    <TagSearchBarBase
      tags={tags}
      canCreate={false}
      tagColorFn={tagColorFn}
      onSelectTag={handleSelect}
      onSearch={handleSearch}
      searchButtonLabel="Search"
      isSearching={isFetching}
      emptyMessage={emptyMessage}
      onChangeQuery={(nextQuery) => {
        const nextValue = nextQuery.q ?? "";
        setInputQuery(nextValue);
        if (validationMessage && nextValue.trim().length >= 2) {
          setValidationMessage(null);
        }
      }}
      placeholder="Search the GBIF Backbone taxonomy…"
      {...props}
    />
  );
}
