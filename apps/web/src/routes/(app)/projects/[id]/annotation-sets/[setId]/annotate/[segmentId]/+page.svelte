<script lang="ts">
  /**
   * AnnotationEditor route — per-segment authoring surface.
   *
   * This route is a thin wrapper around the AnnotationEditor component which
   * owns the query / mutation orchestration. Route params are reactive via
   * `$page.params` so that in-editor navigation (replaceState or goto) between
   * segments reuses the mounted component and just swaps props.
   */
  import { page } from '$app/stores';
  import * as m from '$lib/paraglide/messages';
  import AnnotationEditor from '$lib/components/annotation-sets/AnnotationEditor.svelte';

  const projectId = $derived($page.params.id as string);
  const setId = $derived($page.params.setId as string);
  const segmentId = $derived($page.params.segmentId as string);
</script>

<svelte:head>
  <title>{m.annotation_editor_page_title()}</title>
</svelte:head>

{#key segmentId}
  <AnnotationEditor {projectId} {setId} {segmentId} />
{/key}
