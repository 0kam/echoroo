<script lang="ts">
  /**
   * AnnotationEditor route — per-segment authoring surface.
   *
   * This route is a thin wrapper around the AnnotationEditor component which
   * owns the query / mutation orchestration. Route params are reactive via
   * `$page.params` so that in-editor navigation (replaceState or goto) between
   * segments reuses the mounted component and just swaps props.
   *
   * Participation gate (ToriTore preview): before rendering the editor we fetch
   * the caller's eligibility for the set. When `eligible === false` the editor
   * is replaced by a gate panel that lets the annotator upload their ToriTore
   * result; only after they clear the threshold does the editor unlock.
   */
  import { page } from '$app/stores';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages';
  import { localizeHref } from '$lib/paraglide/runtime';
  import AnnotationEditor from '$lib/components/annotation-sets/AnnotationEditor.svelte';
  import ToritoreGatePanel from '$lib/components/annotation-sets/ToritoreGatePanel.svelte';
  import { getAnnotationSetEligibility } from '$lib/api/me-toritore';

  const projectId = $derived($page.params.id as string);
  const setId = $derived($page.params.setId as string);
  const segmentId = $derived($page.params.segmentId as string);

  const queryClient = useQueryClient();

  // Eligibility is per (project, set, current user). `eligible` is computed
  // server-side (exempt OR no requirement OR score>=required).
  const eligibilityQuery = $derived(
    createQuery({
      queryKey: ['annotation-set-eligibility', projectId, setId],
      queryFn: () => getAnnotationSetEligibility(projectId, setId),
      enabled: !!projectId && !!setId,
      refetchOnWindowFocus: false,
    }),
  );

  const eligibility = $derived($eligibilityQuery.data ?? null);

  /** Re-fetch eligibility after a ToriTore upload so the editor can unlock. */
  async function refetchEligibility(): Promise<void> {
    await queryClient.invalidateQueries({
      queryKey: ['annotation-set-eligibility', projectId, setId],
    });
  }
</script>

<svelte:head>
  <title>{m.annotation_editor_page_title()}</title>
</svelte:head>

{#if $eligibilityQuery.isLoading}
  <div class="mx-auto max-w-5xl px-4 py-6">
    <p class="text-sm text-stone-400">{m.toritore_gate_loading()}</p>
  </div>
{:else if $eligibilityQuery.isError}
  <div class="mx-auto max-w-5xl px-4 py-6">
    <div
      class="rounded-lg border border-danger/30 bg-danger-light p-4 text-sm text-danger"
      role="alert"
    >
      {m.toritore_gate_eligibility_error()}
    </div>
  </div>
{:else if eligibility && !eligibility.eligible}
  <div class="mx-auto max-w-5xl px-4 py-6">
    <!-- Breadcrumb back to the set so a gated annotator isn't stranded. -->
    <nav class="mb-4 flex items-center gap-2 text-sm text-stone-500">
      <a
        href={localizeHref(`/projects/${projectId}/annotation-sets/${setId}`)}
        class="hover:text-stone-900 dark:hover:text-stone-200"
      >
        {m.annotation_sets_detail_breadcrumb()}
      </a>
    </nav>
    <ToritoreGatePanel
      required={eligibility.required}
      myLatestTotalScore={eligibility.my_latest_total_score}
      onUploaded={refetchEligibility}
    />
  </div>
{:else}
  {#key segmentId}
    <AnnotationEditor {projectId} {setId} {segmentId} />
  {/key}
{/if}
