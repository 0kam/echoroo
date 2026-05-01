<script lang="ts">
  /**
   * FileUpload - Multi-step audio file upload workflow.
   *
   * Steps: select → hashing → creating → uploading → completing → polling → done | error
   *
   * Sub-components:
   * - FileDropZone: drag-and-drop area
   * - SelectedFileList: list of queued files
   * - UploadProgressPanel: per-file upload progress
   */

  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages';
  import {
    createUploadSession,
    completeUploadSession,
    fetchUploadSessionStatus,
    computeFileSHA256,
    uploadFileToPresignedUrl,
  } from '$lib/api/uploads';
  import { startImport } from '$lib/api/datasets';
  import type {
    UploadSessionStatus,
    UploadFilePresignedResponse,
    CreateUploadSessionResponse,
  } from '$lib/types/data';
  import FileDropZone from './FileDropZone.svelte';
  import SelectedFileList from './SelectedFileList.svelte';
  import UploadProgressPanel from './UploadProgressPanel.svelte';

  interface Props {
    projectId: string;
    datasetId: string;
    onComplete?: () => void;
  }

  let { projectId, datasetId, onComplete }: Props = $props();

  const queryClient = useQueryClient();

  // ── Constants ──────────────────────────────────────────────────────────────
  const ACCEPTED_EXTENSIONS = ['.wav', '.flac', '.mp3', '.ogg', '.opus'];
  const ACCEPTED_MIME_TYPES = [
    'audio/wav', 'audio/x-wav', 'audio/flac', 'audio/x-flac',
    'audio/mpeg', 'audio/mp3', 'audio/ogg', 'audio/opus',
  ];
  const MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024 * 1024; // 1 GB
  const MAX_FILE_COUNT = 500;
  const UPLOAD_CONCURRENCY = 3;

  // ── Workflow step ──────────────────────────────────────────────────────────
  type WorkflowStep =
    | 'select'      // Selecting files
    | 'hashing'     // Computing SHA-256 checksums
    | 'creating'    // Creating the upload session
    | 'uploading'   // Uploading files to presigned URLs
    | 'completing'  // Calling complete endpoint
    | 'polling'     // Polling session status (validating/importing)
    | 'done'        // All done (imported)
    | 'error';      // Terminal error

  // ── State ──────────────────────────────────────────────────────────────────
  let step = $state<WorkflowStep>('select');
  let isDragOver = $state(false);
  let selectedFiles = $state<File[]>([]);
  let errorMessage = $state<string | null>(null);

  let hashingProgress = $state(0);
  let fileUploadProgress = $state<Record<number, number>>({});

  let sessionId = $state<string | null>(null);
  let _sessionData = $state<CreateUploadSessionResponse | null>(null);

  // ── Derived values ─────────────────────────────────────────────────────────
  const totalBytes = $derived(selectedFiles.reduce((sum, f) => sum + f.size, 0));

  const overallUploadPercent = $derived(() => {
    if (selectedFiles.length === 0) return 0;
    const total = Object.values(fileUploadProgress).reduce((a, b) => a + b, 0);
    return Math.round(total / selectedFiles.length);
  });

  const isPolling = $derived(step === 'polling');

  const statusQuery = $derived(
    createQuery({
      queryKey: ['upload-session-status', projectId, datasetId, sessionId],
      queryFn: () => fetchUploadSessionStatus(projectId, datasetId, sessionId!),
      refetchInterval: isPolling ? 2000 : false,
      enabled: isPolling && sessionId !== null,
    })
  );

  let importTriggered = $state(false);

  // Watch polling results: trigger import when validated, finish when imported
  $effect(() => {
    if (!isPolling) return;
    const data = $statusQuery.data;
    if (!data) return;

    if (data.status === 'validated' && !importTriggered && sessionId) {
      importTriggered = true;
      startImport(projectId, datasetId, {
        source: `upload-session://${sessionId}`,
      }).catch((err) => {
        step = 'error';
        errorMessage = err instanceof Error ? err.message : m.file_upload_import_start_failed();
      });
    } else if (data.status === 'imported') {
      step = 'done';
      queryClient.invalidateQueries({ queryKey: ['dataset', projectId, datasetId] });
      queryClient.invalidateQueries({ queryKey: ['import-status', projectId, datasetId] });
      onComplete?.();
    } else if (data.status === 'failed') {
      step = 'error';
      errorMessage = data.error ?? m.file_upload_import_server_failed();
    }
  });

  // ── File validation ────────────────────────────────────────────────────────

  function isAcceptedFile(file: File): boolean {
    const lowerName = file.name.toLowerCase();
    const hasValidExt = ACCEPTED_EXTENSIONS.some((ext) => lowerName.endsWith(ext));
    const hasValidMime =
      ACCEPTED_MIME_TYPES.includes(file.type) || file.type === '' || file.type.startsWith('audio/');
    return hasValidExt || hasValidMime;
  }

  function validateFiles(files: File[]): { valid: File[]; errors: string[] } {
    const errors: string[] = [];
    const valid: File[] = [];

    for (const file of files) {
      if (!isAcceptedFile(file)) {
        errors.push(m.file_upload_invalid_format({ name: file.name }));
        continue;
      }
      if (file.size > MAX_FILE_SIZE_BYTES) {
        errors.push(m.file_upload_exceeds_size({ name: file.name }));
        continue;
      }
      valid.push(file);
    }

    return { valid, errors };
  }

  function addFiles(incoming: File[]) {
    const { valid, errors } = validateFiles(incoming);

    errorMessage = errors.length > 0 ? errors.join('\n') : null;

    const existingNames = new Set(selectedFiles.map((f) => f.name));
    const newFiles = valid.filter((f) => !existingNames.has(f.name));
    const combined = [...selectedFiles, ...newFiles];

    if (combined.length > MAX_FILE_COUNT) {
      errorMessage = m.file_upload_max_count_exceeded({ max: MAX_FILE_COUNT });
      selectedFiles = combined.slice(0, MAX_FILE_COUNT);
    } else {
      selectedFiles = combined;
    }
  }

  function removeFile(index: number) {
    selectedFiles = selectedFiles.filter((_, i) => i !== index);
  }

  // ── Upload workflow ────────────────────────────────────────────────────────

  async function startUpload() {
    if (selectedFiles.length === 0) return;

    errorMessage = null;
    step = 'hashing';
    hashingProgress = 0;

    try {
      // Phase 1: Compute checksums
      const fileRequests = [];
      for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i];
        if (!file) continue;
        const checksum = await computeFileSHA256(file);
        fileRequests.push({
          filename: file.name,
          size: file.size,
          checksum_sha256: checksum,
        });
        hashingProgress = Math.round(((i + 1) / selectedFiles.length) * 100);
      }

      // Phase 2: Create upload session
      step = 'creating';
      const session = await createUploadSession(projectId, datasetId, { files: fileRequests });
      sessionId = session.session_id;
      _sessionData = session;

      const presignedMap = new Map<string, UploadFilePresignedResponse>(
        session.files.map((f) => [f.original_filename, f])
      );

      // Phase 3: Upload files to presigned URLs
      step = 'uploading';
      fileUploadProgress = {};
      await uploadFilesConcurrently(selectedFiles, presignedMap);

      // Phase 4: Signal completion
      step = 'completing';
      await completeUploadSession(projectId, datasetId, session.session_id);

      // Phase 5: Poll for validation + import
      step = 'polling';
    } catch (e) {
      step = 'error';
      errorMessage = e instanceof Error ? e.message : m.file_upload_unexpected_error();
    }
  }

  async function uploadFilesConcurrently(
    files: File[],
    presignedMap: Map<string, UploadFilePresignedResponse>
  ): Promise<void> {
    const queue = [...files.entries()];
    const inFlight: Set<Promise<void>> = new Set();

    function startNext(): Promise<void> | null {
      const entry = queue.shift();
      if (!entry) return null;
      const [index, file] = entry;

      const presigned = presignedMap.get(file.name);
      if (!presigned) {
        fileUploadProgress[index] = 100;
        return Promise.resolve();
      }

      const promise = uploadFileToPresignedUrl(presigned.upload_url, file, (percent) => {
        fileUploadProgress = { ...fileUploadProgress, [index]: percent };
      }).finally(() => {
        inFlight.delete(promise);
      });

      inFlight.add(promise);
      return promise;
    }

    for (let i = 0; i < UPLOAD_CONCURRENCY && queue.length > 0; i++) {
      startNext();
    }

    while (inFlight.size > 0) {
      await Promise.race(inFlight);
      while (inFlight.size < UPLOAD_CONCURRENCY && queue.length > 0) {
        startNext();
      }
    }
  }

  function getSessionStatusLabel(status: UploadSessionStatus): string {
    switch (status) {
      case 'issued':     return m.upload_status_issued();
      case 'uploaded':   return m.upload_status_uploaded();
      case 'validating': return m.upload_status_validating();
      case 'validated':  return m.upload_status_validated();
      case 'importing':  return m.upload_status_importing();
      case 'imported':   return m.upload_status_imported();
      case 'failed':     return m.upload_status_failed();
      default:           return status;
    }
  }

  function getSessionStatusClasses(status: UploadSessionStatus): string {
    switch (status) {
      case 'issued':
      case 'uploaded':
        return 'bg-warning-light text-warning';
      case 'validating':
      case 'importing':
        return 'bg-primary-100 text-primary-800 dark:bg-primary-900/30 dark:text-primary-400';
      case 'validated':
      case 'imported':
        return 'bg-success-light text-success';
      case 'failed':
        return 'bg-danger-light text-danger';
      default:
        return 'bg-stone-100 text-stone-800 dark:bg-stone-700 dark:text-stone-300';
    }
  }

  function resetToSelect() {
    step = 'select';
    selectedFiles = [];
    errorMessage = null;
    hashingProgress = 0;
    fileUploadProgress = {};
    sessionId = null;
    _sessionData = null;
    importTriggered = false;
  }
</script>

<div class="rounded-lg border border-card bg-surface-card p-6">
  <h3 class="mb-4 text-base font-semibold text-stone-900">{m.file_upload_heading()}</h3>

  <!-- ── Step: File Selection ─────────────────────────────────────────────── -->
  {#if step === 'select'}
    <FileDropZone
      {isDragOver}
      onFilesAdded={addFiles}
      onDragOver={() => { isDragOver = true; }}
      onDragLeave={() => { isDragOver = false; }}
    />

    <!-- Validation error banner -->
    {#if errorMessage}
      <div class="mb-4 rounded-md border border-danger/20 bg-danger-light p-3">
        <div class="flex items-start gap-2">
          <svg class="mt-0.5 h-4 w-4 flex-shrink-0 text-danger" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <p class="whitespace-pre-wrap text-sm text-danger">{errorMessage}</p>
        </div>
      </div>
    {/if}

    {#if selectedFiles.length > 0}
      <SelectedFileList
        files={selectedFiles}
        {totalBytes}
        onRemove={removeFile}
        onClearAll={() => { selectedFiles = []; }}
        onUpload={startUpload}
      />
    {/if}
  {/if}

  <!-- ── Step: Hashing ────────────────────────────────────────────────────── -->
  {#if step === 'hashing'}
    <div class="space-y-3">
      <div class="flex items-center gap-3">
        <svg class="h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        <span class="text-sm font-medium text-stone-700">{m.file_upload_hashing()}</span>
        <span class="ml-auto text-sm text-stone-500">{hashingProgress}%</span>
      </div>
      <div class="h-2 overflow-hidden rounded-full bg-stone-200">
        <div class="h-full bg-primary-600 transition-all duration-200" style="width: {hashingProgress}%"></div>
      </div>
      <p class="text-xs text-stone-400">
        {m.file_upload_hashing_hint({ count: selectedFiles.length })}
      </p>
    </div>
  {/if}

  <!-- ── Step: Creating session ───────────────────────────────────────────── -->
  {#if step === 'creating'}
    <div class="flex items-center gap-3">
      <svg class="h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24" aria-hidden="true">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span class="text-sm font-medium text-stone-700">{m.file_upload_creating_session()}</span>
    </div>
  {/if}

  <!-- ── Step: Uploading files ────────────────────────────────────────────── -->
  {#if step === 'uploading'}
    <UploadProgressPanel
      files={selectedFiles}
      {fileUploadProgress}
      overallPercent={overallUploadPercent()}
    />
  {/if}

  <!-- ── Step: Completing ─────────────────────────────────────────────────── -->
  {#if step === 'completing'}
    <div class="flex items-center gap-3">
      <svg class="h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24" aria-hidden="true">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span class="text-sm font-medium text-stone-700">{m.file_upload_finalizing()}</span>
    </div>
  {/if}

  <!-- ── Step: Polling (validating / importing) ───────────────────────────── -->
  {#if step === 'polling'}
    {@const status = $statusQuery.data}
    <div class="space-y-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <svg class="h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          <span class="text-sm font-medium text-stone-700">
            {status ? getSessionStatusLabel(status.status) : m.common_processing()}
          </span>
        </div>
        {#if status}
          <span class="rounded-md px-2.5 py-1 text-xs font-medium {getSessionStatusClasses(status.status)}">
            {status.status}
          </span>
        {/if}
      </div>

      {#if status}
        <div>
          <div class="mb-1.5 flex justify-between text-sm text-stone-500">
            {#if status.status === 'validating' || status.status === 'validated'}
              <span>{m.file_upload_validated({ validated: status.validated_files, total: status.total_files })}</span>
            {:else}
              <span>{m.file_upload_imported({ imported: status.imported_files, total: status.total_files })}</span>
            {/if}
            <span>{status.progress_percent.toFixed(1)}%</span>
          </div>
          <div class="h-2 overflow-hidden rounded-full bg-stone-200">
            <div
              class="h-full bg-primary-600 transition-all duration-300"
              style="width: {status.progress_percent}%"
            ></div>
          </div>
        </div>

        <!-- Invalid files warning -->
        {#if status.files.some((f) => f.status === 'invalid')}
          <div class="rounded-md border border-warning/20 bg-warning-light p-3">
            <p class="mb-1.5 text-xs font-medium text-warning">{m.file_upload_validation_warning()}</p>
            <ul class="space-y-1">
              {#each status.files.filter((f) => f.status === 'invalid') as invalidFile}
                <li class="text-xs text-warning">
                  <span class="font-medium">{invalidFile.original_filename}</span>
                  {#if invalidFile.validation_error}
                    &mdash; {invalidFile.validation_error}
                  {/if}
                </li>
              {/each}
            </ul>
          </div>
        {/if}
      {/if}
    </div>
  {/if}

  <!-- ── Step: Done ───────────────────────────────────────────────────────── -->
  {#if step === 'done'}
    {@const status = $statusQuery.data}
    <div class="space-y-4">
      <div class="flex items-center gap-3 rounded-md border border-success/30 bg-success-light p-4">
        <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-success text-white">
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <div>
          <p class="font-medium text-success">{m.file_upload_complete()}</p>
          {#if status}
            <p class="text-sm text-success">
              {m.file_upload_success({ count: status.imported_files })}
            </p>
          {/if}
        </div>
      </div>

      {#if status?.files.some((f) => f.status === 'invalid')}
        <div class="rounded-md border border-warning/20 bg-warning-light p-3">
          <p class="mb-1.5 text-xs font-medium text-warning">
            {m.file_upload_import_warning({ count: status.files.filter((f) => f.status === 'invalid').length })}
          </p>
          <ul class="space-y-1">
            {#each status.files.filter((f) => f.status === 'invalid') as invalidFile}
              <li class="text-xs text-warning">
                <span class="font-medium">{invalidFile.original_filename}</span>
                {#if invalidFile.validation_error}
                  &mdash; {invalidFile.validation_error}
                {/if}
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      <div class="flex justify-end">
        <button
          onclick={resetToSelect}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50"
        >
          {m.file_upload_more()}
        </button>
      </div>
    </div>
  {/if}

  <!-- ── Step: Error ──────────────────────────────────────────────────────── -->
  {#if step === 'error'}
    <div class="space-y-4">
      <div class="rounded-md border border-danger/20 bg-danger-light p-4">
        <div class="mb-2 flex items-center gap-2">
          <svg class="h-4 w-4 flex-shrink-0 text-danger" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span class="text-sm font-semibold text-danger">{m.file_upload_error()}</span>
        </div>
        <p class="whitespace-pre-wrap break-words font-mono text-sm text-danger">
          {errorMessage ?? m.file_upload_unknown_error()}
        </p>
      </div>

      <div class="flex justify-end">
        <button
          onclick={resetToSelect}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50"
        >
          {m.file_upload_try_again()}
        </button>
      </div>
    </div>
  {/if}
</div>
