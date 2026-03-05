<script lang="ts">
  /**
   * Reports page for exporting project data.
   * Provides export options for Detection CSV and ML Training Dataset (ZIP).
   */

  import { page } from '$app/stores';
  import DetectionExportDialog from '$lib/components/detection/DetectionExportDialog.svelte';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  const projectId = $derived($page.params.id as string);

  let isDialogOpen = $state(false);
  let dialogFormat = $state<'csv' | 'ml-dataset'>('csv');

  function openExportDialog(format: 'csv' | 'ml-dataset') {
    dialogFormat = format;
    isDialogOpen = true;
  }

  function closeExportDialog() {
    isDialogOpen = false;
  }

  interface ExportCard {
    id: string;
    title: string;
    description: string;
    details: string[];
    icon: string;
    buttonLabel: string;
    format: 'csv' | 'ml-dataset';
  }

  const exportCards: ExportCard[] = [
    {
      id: 'detection-csv',
      title: 'Detection CSV',
      description: 'Export all detection results as a CSV file for analysis in spreadsheet tools or custom scripts.',
      details: [
        'recording_filename',
        'start_time / end_time',
        'species, confidence',
        'source, model_name, model_version',
        'verified, verified_by',
      ],
      icon: 'M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
      buttonLabel: 'Export CSV',
      format: 'csv',
    },
    {
      id: 'ml-training-dataset',
      title: 'ML Training Dataset',
      description:
        'Export a complete training dataset package as a ZIP file, suitable for fine-tuning ML models.',
      details: [
        'Audio clips (.wav)',
        'annotations.csv',
        'metadata.json',
        'README.txt',
      ],
      icon: 'M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4',
      buttonLabel: 'Export ZIP',
      format: 'ml-dataset',
    },
  ];
</script>

<svelte:head>
  <title>{m.report_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-4xl px-6 py-8">
  <!-- Page header -->
  <header class="mb-8">
    <nav class="mb-2 flex items-center gap-2 text-sm text-gray-500">
      <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-gray-900">{m.report_breadcrumb_project()}</a>
      <span>/</span>
      <span class="font-medium text-gray-900">{m.report_heading()}</span>
    </nav>
    <h1 class="text-2xl font-bold text-gray-900">{m.report_heading()}</h1>
    <p class="mt-1 text-sm text-gray-500">{m.report_description()}</p>
  </header>

  <!-- Export option cards -->
  <div class="flex flex-col gap-6">
    {#each exportCards as card (card.id)}
      <div class="rounded-lg border border-gray-200 bg-white p-6">
        <div class="flex items-start gap-4">
          <!-- Icon -->
          <div class="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-lg bg-blue-50">
            <svg class="h-6 w-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={card.icon} />
            </svg>
          </div>

          <!-- Content -->
          <div class="min-w-0 flex-1">
            <h2 class="text-lg font-semibold text-gray-900">{card.title}</h2>
            <p class="mt-1 text-sm text-gray-500">{card.description}</p>

            <!-- Included fields -->
            <div class="mt-3">
              <p class="mb-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">{m.report_includes_label()}</p>
              <ul class="flex flex-wrap gap-2">
                {#each card.details as detail}
                  <li class="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600">
                    {detail}
                  </li>
                {/each}
              </ul>
            </div>
          </div>

          <!-- Action button -->
          <div class="ml-4 flex-shrink-0">
            <button
              type="button"
              onclick={() => openExportDialog(card.format)}
              class="flex items-center gap-2 rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 hover:border-blue-300 transition-colors"
              aria-label={card.buttonLabel}
            >
              <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={card.icon} />
              </svg>
              {card.buttonLabel}
            </button>
          </div>
        </div>
      </div>
    {/each}
  </div>
</div>

<!-- Export dialog -->
<DetectionExportDialog
  {projectId}
  isOpen={isDialogOpen}
  initialFormat={dialogFormat}
  onClose={closeExportDialog}
/>
