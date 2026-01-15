import { useCallback } from "react";

import useSoundEventAnnotation from "@/app/hooks/api/useSoundEventAnnotation";

import useStore from "@/app/store";

import SelectedSoundEventAnnotationBase from "@/lib/components/sound_event_annotations/SelectedSoundEventAnnotation";

import type { SoundEventAnnotation, Tag } from "@/lib/types";

import ProjectTagSearch from "../tags/ProjectTagsSearch";

export default function SelectedSoundEventAnnotation({
  soundEventAnnotation,
}: {
  soundEventAnnotation: SoundEventAnnotation;
}) {
  const tagColorFn = useStore((state) => state.getTagColor);

  const { data, addTag, removeTag, addNote, updateNote, removeNote } =
    useSoundEventAnnotation({
      uuid: soundEventAnnotation.uuid,
      soundEventAnnotation,
    });

  const handleAddTag = useCallback(
    (tag: Tag) => {
      const annotation = data || soundEventAnnotation;
      addTag.mutate({ soundEventAnnotation: annotation, tag });
    },
    [data, soundEventAnnotation, addTag],
  );

  const handleRemoveTag = useCallback(
    (tag: Tag) => {
      const annotation = data || soundEventAnnotation;
      removeTag.mutate({ soundEventAnnotation: annotation, tag });
    },
    [data, soundEventAnnotation, removeTag],
  );

  return (
    <SelectedSoundEventAnnotationBase
      soundEventAnnotation={data || soundEventAnnotation}
      onAddSoundEventAnnotationTag={handleAddTag}
      onDeleteSoundEventAnnotationTag={handleRemoveTag}
      TagSearchBar={ProjectTagSearch}
      tagColorFn={tagColorFn}
      onCreateSoundEventAnnotationNote={addNote.mutate}
      onUpdateSoundEventAnnotationNote={(note, data) =>
        updateNote.mutate({ note, data })
      }
      onDeleteSoundEventAnnotationNote={removeNote.mutate}
    />
  );
}
