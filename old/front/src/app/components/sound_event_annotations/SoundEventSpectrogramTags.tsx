import { useCallback } from "react";

import useSoundEventAnnotation from "@/app/hooks/api/useSoundEventAnnotation";

import useStore from "@/app/store";

import {
  SoundEventSpectrogramTagsBase,
  SoundEventSpectrogramTagsProps,
} from "@/lib/components/spectrograms/SpectrogramTags";

import type { SoundEventAnnotation, Tag } from "@/lib/types";

import ProjectTagSearch from "../tags/ProjectTagsSearch";

export default function SoundEventAnnotationTags({
  soundEvent,
  ...props
}: SoundEventSpectrogramTagsProps) {
  const tagColorFn = useStore((state) => state.getTagColor);

  const handleAddTagCallback = useCallback(
    (tag: Tag) => {
      if (props.onAddTag) {
        props.onAddTag(soundEvent, tag);
      }
    },
    [props, soundEvent],
  );

  const handleRemoveTagCallback = useCallback(
    (tag: Tag) => {
      if (props.onRemoveTag) {
        props.onRemoveTag(soundEvent, tag);
      }
    },
    [props, soundEvent],
  );

  const { data, addTag, removeTag } = useSoundEventAnnotation({
    uuid: soundEvent.uuid,
    soundEventAnnotation: soundEvent,
    onAddTag: handleAddTagCallback,
    onRemoveTag: handleRemoveTagCallback,
  });

  const handleAddTag = useCallback(
    (annotation: SoundEventAnnotation, tag: Tag) => {
      addTag.mutate({
        soundEventAnnotation: annotation,
        tag,
      });
    },
    [addTag],
  );

  const handleRemoveTag = useCallback(
    (annotation: SoundEventAnnotation, tag: Tag) => {
      removeTag.mutate({
        soundEventAnnotation: annotation,
        tag,
      });
    },
    [removeTag],
  );

  return (
    <SoundEventSpectrogramTagsBase
      soundEvent={data || soundEvent}
      {...props}
      tagColorFn={tagColorFn}
      onAddTag={handleAddTag}
      onRemoveTag={handleRemoveTag}
      tagSearchBarComponent={ProjectTagSearch}
    />
  );
}
