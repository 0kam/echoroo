import {
  type ChangeEvent,
  type InputHTMLAttributes,
  type KeyboardEvent,
  forwardRef,
  useCallback,
  useMemo,
  useState,
} from "react";

import { Input } from "@/lib/components/inputs/index";
import Tag from "@/lib/components/tags/Tag";
import Button from "@/lib/components/ui/Button";

import type { Tag as TagType } from "@/lib/types";
import type { Color } from "@/lib/utils/tags";

type Query = {
  q: string;
  key: string | null;
  value: string | null;
};

export type TagSearchBarProps = {
  tags?: TagType[];
  canCreate?: boolean;
  onBlur?: () => void;
  onKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void;
  onCreateTag?: (tag: TagType) => void;
  onSelectTag?: (tag: TagType) => void;
  onSearch?: () => void;
  searchButtonLabel?: string;
  isSearching?: boolean;
  emptyMessage?: string;
  tagColorFn?: (tag: TagType) => Color;
};

type TagSearchBarExpandedProps = TagSearchBarProps & {
  onChangeQuery?: (query: Query) => void;
} & Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "onSelect" | "onChange" | "onKeyDown" | "onBlur"
>;

const _emptyTags: TagType[] = [];

export type TagSearchBarComponentProps = TagSearchBarExpandedProps;

const TagSearchBar = forwardRef<HTMLInputElement, TagSearchBarExpandedProps>(
  function TagSearchBar(
    {
      tags = _emptyTags,
      tagColorFn,
      canCreate = false,
      onSelectTag,
      onChangeQuery,
      onKeyDown,
      onCreateTag,
      onSearch,
      searchButtonLabel,
      isSearching = false,
      emptyMessage,
      disabled,
      ...props
    },
    ref,
  ) {
    const [query, setQuery] = useState<Query>({
      q: "",
      key: null,
      value: null,
    });
    const [submittedQuery, setSubmittedQuery] = useState<string | null>(null);

    const isManualSearch = typeof onSearch === "function";
    const trimmedQuery = useMemo(() => query.q.trim(), [query.q]);

    const handleQueryChange = useCallback(
      (event: ChangeEvent<HTMLInputElement>) => {
        const q = event.target.value;
        const [key, value] = q.split(":", 2);
        const nextQuery =
          value == null ? { q, key: null, value: null } : { q, key, value };
        setQuery(nextQuery);
        setSubmittedQuery(null);
        onChangeQuery?.(nextQuery);
      },
      [onChangeQuery],
    );

    const handleCreateShortcut = useCallback(() => {
      if (!canCreate) return;
      if (!(query.key && query.value)) return;
      onCreateTag?.({
        key: query.key,
        value: query.value,
      });
    }, [canCreate, onCreateTag, query.key, query.value]);

    const canTriggerSearch = trimmedQuery.length >= 2;

    const handleSearch = useCallback(() => {
      if (!isManualSearch) return;
      if (!canTriggerSearch) return;
      setSubmittedQuery(trimmedQuery);
      onSearch?.();
    }, [isManualSearch, canTriggerSearch, trimmedQuery, onSearch]);

    const internalKeyDown = useCallback(
      (event: KeyboardEvent<HTMLInputElement>) => {
        if (event.key === "Enter" && event.shiftKey) {
          event.preventDefault();
          handleCreateShortcut();
          return;
        }
        if (event.key === "Enter" && !event.shiftKey && isManualSearch) {
          event.preventDefault();
          handleSearch();
          return;
        }
        onKeyDown?.(event);
      },
      [handleCreateShortcut, handleSearch, isManualSearch, onKeyDown],
    );

    const showResults =
      !isManualSearch || (!!submittedQuery && submittedQuery === trimmedQuery);

    const filteredTags = useMemo(() => {
      if (isManualSearch) return tags;
      const lowercase = trimmedQuery.toLowerCase();
      if (!lowercase) return tags;
      return tags.filter((tag) => {
        const candidates: string[] = [];
        if (tag.canonical_name) {
          candidates.push(tag.canonical_name);
        }
        if (tag.vernacular_name) {
          candidates.push(tag.vernacular_name);
        }
        if (tag.value) {
          candidates.push(tag.value);
        }
        if (tag.key) {
          candidates.push(tag.key);
        }
        if (tag.canonical_name) {
          const parts = tag.canonical_name.toLowerCase().split(/\s+/).filter(Boolean);
          candidates.push(...parts);
        }
        return candidates.some((text) =>
          text.toLowerCase().includes(lowercase),
        );
      });
    }, [isManualSearch, tags, trimmedQuery]);

    const hasResults = filteredTags.length > 0;

    return (
      <div className="flex flex-col gap-3">
        <div className="flex items-start gap-2">
          <Input
            ref={ref}
            autoFocus={props.autoFocus}
            value={query.q}
            onChange={handleQueryChange}
            onKeyDown={internalKeyDown}
            disabled={disabled}
            {...props}
          />
          {isManualSearch && (
            <Button
              type="button"
              variant="primary"
              disabled={disabled || isSearching || !canTriggerSearch}
              className="whitespace-nowrap"
              onClick={handleSearch}
            >
              {isSearching ? "Searching…" : searchButtonLabel ?? "Search"}
            </Button>
          )}
        </div>
        {showResults && (
          <div className="rounded-md border border-stone-200 dark:border-stone-700 max-h-64 overflow-y-auto">
            {hasResults ? (
              <ul className="divide-y divide-stone-200 dark:divide-stone-700">
                {filteredTags.map((tag) => (
                  <li key={`${tag.key}:${tag.value}`}>
                    <button
                      type="button"
                      className="w-full text-left px-3 py-2 hover:bg-stone-100 dark:hover:bg-stone-700"
                      onClick={() => onSelectTag?.(tag)}
                      disabled={disabled}
                    >
                      <Tag
                        disabled
                        className="pointer-events-none"
                        tag={tag}
                        {...(tagColorFn
                          ? tagColorFn(tag)
                          : { color: "stone", level: 3 })}
                      />
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="px-3 py-2 text-sm text-stone-500">
                {emptyMessage ?? "No results."}
              </div>
            )}
          </div>
        )}
      </div>
    );
  },
);

export default TagSearchBar;
