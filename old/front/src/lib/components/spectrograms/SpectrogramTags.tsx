import classNames from "classnames";
import { useMemo } from "react";
import type { ComponentProps, FC, ReactNode } from "react";

import { CloseIcon } from "@/lib/components/icons";

import useElementSize from "@/lib/hooks/utils/useElementSize";

import type {
  Dimensions,
  SoundEventAnnotation,
  SpectrogramWindow,
  Tag as TagType,
} from "@/lib/types";
import { isGeometryInWindow } from "@/lib/utils/geometry";
import {
  getLabelPosition,
  getTagKey,
  getTagLabel,
  type Color,
  type TagElement,
} from "@/lib/utils/tags";

import TagSearchBarBase, {
  type TagSearchBarProps,
} from "../tags/TagSearchBar";

import AddTagButton from "../tags/AddTagButton";

export default function SpectrogramTags({
  children,
  soundEvents,
  viewport,
  SoundEventTags = SoundEventSpectrogramTagsBase,
  availableTags = [],
  TagSearchComponent = TagSearchBarBase,
  emptyMessage,
  ...props
}: {
  children: ReactNode;
  viewport: SpectrogramWindow;
  soundEvents: SoundEventAnnotation[];
  SoundEventTags?: FC<SoundEventSpectrogramTagsProps>;
  availableTags?: TagType[];
  TagSearchComponent?: FC<TagSearchBarProps>;
  emptyMessage?: string;
} & Omit<SoundEventSpectrogramTagsProps, "soundEvent" | "dimensions">) {
  const { size: dimensions, ref } = useElementSize<HTMLDivElement>();

  const soundEventsInWindow = useMemo(() => {
    return soundEvents.filter((soundEvent) => {
      return isGeometryInWindow(soundEvent.sound_event.geometry, viewport);
    });
  }, [soundEvents, viewport]);

  return (
    <div className="relative w-full h-full rounded" ref={ref}>
      {children}
      {soundEventsInWindow.map((soundEvent) => (
        <SoundEventTags
          key={soundEvent.uuid}
          viewport={viewport}
          soundEvent={soundEvent}
          dimensions={dimensions}
          availableTags={availableTags}
          tagSearchBarComponent={TagSearchComponent}
          emptyMessage={emptyMessage}
          {...props}
        />
      ))}
    </div>
  );
}

export type SoundEventSpectrogramTagsProps = {
  soundEvent: SoundEventAnnotation;
  viewport: SpectrogramWindow;
  dimensions: Dimensions;
  enabled?: boolean;
  onAddTag?: (soundEvent: SoundEventAnnotation, tag: TagType) => void;
  onRemoveTag?: (soundEvent: SoundEventAnnotation, tag: TagType) => void;
  availableTags?: TagType[];
  tagSearchBarComponent?: FC<TagSearchBarProps>;
  emptyMessage?: string;
};

const DEFAULT_COLOR: Color = { color: "stone", level: 3 };

export function SoundEventSpectrogramTagsBase({
  soundEvent,
  viewport,
  dimensions,
  enabled = true,
  tagColorFn,
  onRemoveTag,
  onAddTag,
  availableTags = [],
  tagSearchBarComponent = TagSearchBarBase,
  emptyMessage,
  ...props
}: SoundEventSpectrogramTagsProps & {
  tagColorFn?: (tag: TagType) => Color;
  availableTags?: TagType[];
  tagSearchBarComponent?: FC<TagSearchBarProps>;
  emptyMessage?: string;
} & Omit<ComponentProps<typeof AddTagButton>, "onSelectTag">) {
  const { x, y } = getLabelPosition(soundEvent, viewport, dimensions);
  const TagSearchComponent = tagSearchBarComponent;
  const assignedKeys = new Set(
    (soundEvent.tags ?? []).map((tag) => getTagKey(tag)),
  );
  const suggestions = availableTags.filter(
    (tag) => !assignedKeys.has(getTagKey(tag)),
  );
  return (
    <div
      className={classNames(
        "h-5 flex flex-col absolute px-2 text-stone-300 hover:z-50 z-40",
      )}
      style={{
        left: x,
        top: y,
      }}
    >
      <div className="flex relative right-0 flex-col hover:gap-2 -ms-2">
        {soundEvent.tags?.map((tag) => (
          <SpectrogramTag
            key={getTagKey(tag)}
            disabled={!enabled}
            tagColorFn={tagColorFn ?? (() => DEFAULT_COLOR)}
            onClick={() => onRemoveTag?.(soundEvent, tag)}
            tag={tag}
          />
        ))}
      </div>
      {enabled && (
        <AddTagButton
          onSelectTag={(tag) => onAddTag?.(soundEvent, tag)}
          TagSearchBar={TagSearchComponent}
          tags={suggestions}
          tagColorFn={tagColorFn}
          emptyMessage={emptyMessage ?? "No project tags available."}
          disabled={suggestions.length === 0}
          {...props}
        />
      )}
    </div>
  );
}

export function SpectrogramTag({
  tag,
  onClick,
  tagColorFn,
  disabled = false,
}: TagElement & { disabled?: boolean; tagColorFn: (tag: TagType) => Color }) {
  const color = tagColorFn(tag);
  const className = useMemo(() => {
    return `bg-${color.color}-500`;
  }, [color]);
  return (
    <span className="flex flex-row gap-1 items-center px-2 -my-2 rounded-full transition-all group bg-stone-200/0 dark:bg-stone-800/0 hover:bg-stone-200 hover:dark:bg-stone-800">
      <span
        className={`inline-block my-2 w-2 h-2 rounded-full ${className} ring-1 ring-stone-900 opacity-100`}
      ></span>
      <button
        type="button"
        className="hidden flex-row gap-1 items-center opacity-0 transition-all group-hover:flex group-hover:opacity-100 hover:text-red-500 text-stone-800 dark:text-stone-400"
        onClick={onClick}
      >
        <span className="hidden text-xs font-thin whitespace-nowrap opacity-0 transition-all group-hover:inline-block group-hover:opacity-100">
          {tag.key}
        </span>
        <span className="hidden flex-col opacity-0 transition-all group-hover:inline-flex group-hover:opacity-100">
          <span className="text-sm font-medium whitespace-nowrap">
            {getTagLabel(tag)}
          </span>
          {tag.vernacular_name && (
            <span className="text-xs text-stone-500 dark:text-stone-400 font-normal whitespace-nowrap">
              {tag.vernacular_name}
            </span>
          )}
        </span>
        {!disabled && <CloseIcon className="inline-block w-3 h-3 stroke-2" />}
      </button>
    </span>
  );
}
