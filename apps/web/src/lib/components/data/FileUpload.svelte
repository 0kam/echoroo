<script lang="ts">
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
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

  interface Props {
    projectId: string;
    datasetId: string;
    onComplete?: () => void;
  }

  let { projectId, datasetId, onComplete }: Props = $props();

  const queryClient = useQueryClient();

  // -----------------------------------------------
  // Constants
  // -----------------------------------------------
  const ACCEPTED_EXTENSIONS = ['.wav', '.flac', '.mp3', '.ogg', '.opus'];
  const ACCEPTED_MIME_TYPES = [
    'audio/wav',
    'audio/x-wav',
    'audio/flac',
    'audio/x-flac',
    'audio/mpeg',
    'audio/mp3',
    'audio/ogg',
    'audio/opus',
  ];
  const MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024 * 1024; // 1 GB
  const MAX_FILE_COUNT = 500;
  const UPLOAD_CONCURRENCY = 3;

  // -----------------------------------------------
  // Upload workflow steps
  // -----------------------------------------------
  type WorkflowStep =
    | 'select'      // Selecting files
    | 'hashing'     // Computing SHA-256 checksums
    | 'creating'    // Creating the upload session
    | 'uploading'   // Uploading files to presigned URLs
    | 'completing'  // Calling complete endpoint
    | 'polling'     // Polling session status (validating/importing)
    | 'done'        // All done (imported)
    | 'error';      // Terminal error

  // -----------------------------------------------
  // State
  // -----------------------------------------------
  let step = $state<WorkflowStep>('select');
  let isDragOver = $state(false);
  let selectedFiles = $state<File[]>([]);
  let errorMessage = $state<string | null>(null);

  // Hashing progress
  let hashingProgress = $state(0); // 0-100

  // Per-file upload progress (keyed by file index)
  let fileUploadProgress = $state<Record<number, number>>({});

  // Active session
  let sessionId = $state<string | null>(null);
  let sessionData = $state<CreateUploadSessionResponse | null>(null);

  // -----------------------------------------------
  // Derived values
  // -----------------------------------------------
  const totalBytes = $derived(selectedFiles.reduce((sum, f) => sum + f.size, 0));

  const overallUploadPercent = $derived(() => {
    if (selectedFiles.length === 0) return 0;
    const total = Object.values(fileUploadProgress).reduce((a, b) => a + b, 0);
    return Math.round(total / selectedFiles.length);
  });

  // Polling query - active only during validating/importing phases
  const isPolling = $derived(step === 'polling');

  const statusQuery = $derived(
    createQuery({
      queryKey: ['upload-session-status', projectId, datasetId, sessionId],
      queryFn: () => fetchUploadSessionStatus(projectId, datasetId, sessionId!),
      refetchInterval: isPolling ? 2000 : false,
      enabled: isPolling && sessionId !== null,
    })
  );

  // Track whether we've already triggered import for this session
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
        errorMessage = err instanceof Error ? err.message : 'Failed to start import.';
      });
    } else if (data.status === 'imported') {
      step = 'done';
      queryClient.invalidateQueries({ queryKey: ['dataset', projectId, datasetId] });
      queryClient.invalidateQueries({ queryKey: ['import-status', projectId, datasetId] });
      onComplete?.();
    } else if (data.status === 'failed') {
      step = 'error';
      errorMessage = data.error ?? 'Import process failed on the server.';
    }
  });

  // -----------------------------------------------
  // File validation helpers
  // -----------------------------------------------
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
        errors.push(`"${file.name}" is not a supported audio format.`);
        continue;
      }
      if (file.size > MAX_FILE_SIZE_BYTES) {
        errors.push(`"${file.name}" exceeds the 1 GB size limit.`);
        continue;
      }
      valid.push(file);
    }

    return { valid, errors };
  }

  function addFiles(incoming: File[]) {
    const { valid, errors } = validateFiles(incoming);

    if (errors.length > 0) {
      errorMessage = errors.join('\n');
    } else {
      errorMessage = null;
    }

    // Deduplicate by name
    const existingNames = new Set(selectedFiles.map((f) => f.name));
    const newFiles = valid.filter((f) => !existingNames.has(f.name));

    const combined = [...selectedFiles, ...newFiles];
    if (combined.length > MAX_FILE_COUNT) {
      errorMessage = `You may upload at most ${MAX_FILE_COUNT} files at once. Only the first ${MAX_FILE_COUNT} will be used.`;
      selectedFiles = combined.slice(0, MAX_FILE_COUNT);
    } else {
      selectedFiles = combined;
    }
  }

  function removeFile(index: number) {
    selectedFiles = selectedFiles.filter((_, i) => i !== index);
  }

  // -----------------------------------------------
  // Drag-and-drop handlers
  // -----------------------------------------------
  function handleDragOver(event: DragEvent) {
    event.preventDefault();
    isDragOver = true;
  }

  function handleDragLeave() {
    isDragOver = false;
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    isDragOver = false;
    const files = Array.from(event.dataTransfer?.files ?? []);
    addFiles(files);
  }

  function handleFileInputChange(event: Event) {
    const input = event.target as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    addFiles(files);
    // Reset input so same files can be re-added if removed
    input.value = '';
  }

  // -----------------------------------------------
  // Main upload workflow
  // -----------------------------------------------
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
      sessionData = session;

      // Build a map from filename to presigned URL entry
      const presignedMap = new Map<string, UploadFilePresignedResponse>(
        session.files.map((f) => [f.original_filename, f])
      );

      // Phase 3: Upload files to presigned URLs (concurrent, limited to UPLOAD_CONCURRENCY)
      step = 'uploading';
      fileUploadProgress = {};

      await uploadFilesConcurrently(selectedFiles, presignedMap);

      // Phase 4: Signal completion to backend (triggers async validation)
      step = 'completing';
      await completeUploadSession(projectId, datasetId, session.session_id);

      // Phase 5: Poll for validation, then trigger import when validated
      step = 'polling';
    } catch (e) {
      step = 'error';
      errorMessage = e instanceof Error ? e.message : 'An unexpected error occurred during upload.';
    }
  }

  /**
   * Upload files with limited concurrency.
   * UPLOAD_CONCURRENCY files are uploaded simultaneously.
   */
  async function uploadFilesConcurrently(
    files: File[],
    presignedMap: Map<string, UploadFilePresignedResponse>
  ): Promise<void> {
    const queue = [...files.entries()]; // [index, file] pairs
    const inFlight: Set<Promise<void>> = new Set();

    function startNext(): Promise<void> | null {
      const entry = queue.shift();
      if (!entry) return null;
      const [index, file] = entry;

      const presigned = presignedMap.get(file.name);
      if (!presigned) {
        // File was not included in the session (unexpected)
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

    // Fill the initial concurrency slots
    for (let i = 0; i < UPLOAD_CONCURRENCY && queue.length > 0; i++) {
      startNext();
    }

    // Process remaining files as slots free up
    while (inFlight.size > 0) {
      await Promise.race(inFlight);
      while (inFlight.size < UPLOAD_CONCURRENCY && queue.length > 0) {
        startNext();
      }
    }
  }

  // -----------------------------------------------
  // Utility: human-readable file size
  // -----------------------------------------------
  function formatBytes(bytes: number): string {
    if (bytes === 0) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  // -----------------------------------------------
  // Session status helpers
  // -----------------------------------------------
  function getSessionStatusLabel(status: UploadSessionStatus): string {
    switch (status) {
      case 'issued':     return 'Session created';
      case 'uploaded':   return 'Files uploaded';
      case 'validating': return 'Validating files...';
      case 'validated':  return 'Files validated';
      case 'importing':  return 'Importing recordings...';
      case 'imported':   return 'Import complete';
      case 'failed':     return 'Failed';
      default:           return status;
    }
  }

  function getSessionStatusClasses(status: UploadSessionStatus): string {
    switch (status) {
      case 'issued':
      case 'uploaded':
        return 'bg-yellow-100 text-yellow-800';
      case 'validating':
      case 'importing':
        return 'bg-blue-100 text-blue-800';
      case 'validated':
      case 'imported':
        return 'bg-green-100 text-green-800';
      case 'failed':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  }

  function resetToSelect() {
    step = 'select';
    selectedFiles = [];
    errorMessage = null;
    hashingProgress = 0;
    fileUploadProgress = {};
    sessionId = null;
    sessionData = null;
    importTriggered = false;
  }
</script>

<div class="rounded-lg border border-gray-200 bg-white p-6">
  <h3 class="mb-4 text-base font-semibold text-gray-900">Upload Audio Files</h3>

  <!-- ============================================ -->
  <!-- Step: File Selection                         -->
  <!-- ============================================ -->
  {#if step === 'select'}
    <!-- Drop zone -->
    <!-- svelte-ignore a11y_interactive_supports_focus -->
    <div
      class="mb-4 flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 text-center transition-colors
        {isDragOver
          ? 'border-blue-400 bg-blue-50'
          : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'}"
      role="button"
      aria-label="Drop audio files here or click to browse"
      ondragover={handleDragOver}
      ondragleave={handleDragLeave}
      ondrop={handleDrop}
      onclick={() => document.getElementById('file-input')?.click()}
      onkeydown={(e) => e.key === 'Enter' && document.getElementById('file-input')?.click()}
    >
      <svg
        class="mb-3 h-10 w-10 {isDragOver ? 'text-blue-400' : 'text-gray-300'}"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
          d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
      </svg>
      <p class="mb-1 text-sm font-medium text-gray-700">
        {isDragOver ? 'Release to add files' : 'Drag and drop audio files here'}
      </p>
      <p class="text-xs text-gray-400">
        or <span class="text-blue-600 underline">browse</span> &mdash;
        WAV, FLAC, MP3, OGG, OPUS &bull; max 1 GB per file &bull; up to 500 files
      </p>
    </div>

    <input
      id="file-input"
      type="file"
      multiple
      accept=".wav,.flac,.mp3,.ogg,.opus,audio/*"
      class="hidden"
      onchange={handleFileInputChange}
    />

    <!-- Validation error banner -->
    {#if errorMessage}
      <div class="mb-4 rounded-md border border-red-200 bg-red-50 p-3">
        <div class="flex items-start gap-2">
          <svg class="mt-0.5 h-4 w-4 flex-shrink-0 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <p class="whitespace-pre-wrap text-sm text-red-700">{errorMessage}</p>
        </div>
      </div>
    {/if}

    <!-- Selected file list -->
    {#if selectedFiles.length > 0}
      <div class="mb-4">
        <div class="mb-2 flex items-center justify-between">
          <span class="text-sm font-medium text-gray-700">
            {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''} selected
            <span class="font-normal text-gray-400">({formatBytes(totalBytes)})</span>
          </span>
          <button
            onclick={() => (selectedFiles = [])}
            class="text-xs text-gray-400 underline hover:text-gray-600"
          >
            Clear all
          </button>
        </div>

        <ul class="max-h-60 divide-y divide-gray-100 overflow-y-auto rounded-md border border-gray-200">
          {#each selectedFiles as file, i}
            <li class="flex items-center gap-3 px-3 py-2">
              <svg class="h-4 w-4 flex-shrink-0 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
              </svg>
              <span class="min-w-0 flex-1 truncate text-sm text-gray-700">{file.name}</span>
              <span class="flex-shrink-0 text-xs text-gray-400">{formatBytes(file.size)}</span>
              <button
                onclick={() => removeFile(i)}
                class="flex-shrink-0 rounded p-0.5 text-gray-300 hover:bg-gray-100 hover:text-gray-500"
                aria-label="Remove {file.name}"
              >
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <line x1="18" y1="6" x2="6" y2="18" stroke-width="2.5" />
                  <line x1="6" y1="6" x2="18" y2="18" stroke-width="2.5" />
                </svg>
              </button>
            </li>
          {/each}
        </ul>
      </div>

      <div class="flex justify-end">
        <button
          onclick={startUpload}
          class="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
        >
          Upload {selectedFiles.length} File{selectedFiles.length !== 1 ? 's' : ''}
        </button>
      </div>
    {/if}
  {/if}

  <!-- ============================================ -->
  <!-- Step: Hashing                                -->
  <!-- ============================================ -->
  {#if step === 'hashing'}
    <div class="space-y-3">
      <div class="flex items-center gap-3">
        <svg class="h-5 w-5 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        <span class="text-sm font-medium text-gray-700">Computing file checksums...</span>
        <span class="ml-auto text-sm text-gray-500">{hashingProgress}%</span>
      </div>
      <div class="h-2 overflow-hidden rounded-full bg-gray-200">
        <div
          class="h-full bg-blue-600 transition-all duration-200"
          style="width: {hashingProgress}%"
        ></div>
      </div>
      <p class="text-xs text-gray-400">
        Verifying integrity of {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''}.
        This may take a moment for large files.
      </p>
    </div>
  {/if}

  <!-- ============================================ -->
  <!-- Step: Creating session                       -->
  <!-- ============================================ -->
  {#if step === 'creating'}
    <div class="flex items-center gap-3">
      <svg class="h-5 w-5 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span class="text-sm font-medium text-gray-700">Creating upload session...</span>
    </div>
  {/if}

  <!-- ============================================ -->
  <!-- Step: Uploading files                        -->
  <!-- ============================================ -->
  {#if step === 'uploading'}
    <div class="space-y-4">
      <!-- Overall progress -->
      <div>
        <div class="mb-1.5 flex justify-between text-sm text-gray-600">
          <span class="font-medium">Uploading files</span>
          <span>{overallUploadPercent()}%</span>
        </div>
        <div class="h-2 overflow-hidden rounded-full bg-gray-200">
          <div
            class="h-full bg-blue-600 transition-all duration-300"
            style="width: {overallUploadPercent()}%"
          ></div>
        </div>
        <p class="mt-1 text-xs text-gray-400">
          Uploading {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''}
          &mdash; up to {UPLOAD_CONCURRENCY} at a time
        </p>
      </div>

      <!-- Per-file progress list -->
      <ul class="max-h-64 divide-y divide-gray-100 overflow-y-auto rounded-md border border-gray-200">
        {#each selectedFiles as file, i}
          {@const pct = fileUploadProgress[i] ?? 0}
          <li class="px-3 py-2">
            <div class="mb-1 flex items-center gap-2">
              {#if pct >= 100}
                <svg class="h-3.5 w-3.5 flex-shrink-0 text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
                </svg>
              {:else if pct > 0}
                <svg class="h-3.5 w-3.5 flex-shrink-0 animate-spin text-blue-500" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
              {:else}
                <div class="h-3.5 w-3.5 flex-shrink-0 rounded-full border-2 border-gray-200"></div>
              {/if}
              <span class="min-w-0 flex-1 truncate text-xs text-gray-700">{file.name}</span>
              <span class="flex-shrink-0 text-xs text-gray-400">{pct}%</span>
            </div>
            <div class="h-1 overflow-hidden rounded-full bg-gray-100">
              <div
                class="h-full transition-all duration-200 {pct >= 100 ? 'bg-green-500' : 'bg-blue-500'}"
                style="width: {pct}%"
              ></div>
            </div>
          </li>
        {/each}
      </ul>
    </div>
  {/if}

  <!-- ============================================ -->
  <!-- Step: Completing                             -->
  <!-- ============================================ -->
  {#if step === 'completing'}
    <div class="flex items-center gap-3">
      <svg class="h-5 w-5 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span class="text-sm font-medium text-gray-700">Finalizing upload and starting import...</span>
    </div>
  {/if}

  <!-- ============================================ -->
  <!-- Step: Polling (validating / importing)       -->
  <!-- ============================================ -->
  {#if step === 'polling'}
    {@const status = $statusQuery.data}
    <div class="space-y-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <svg class="h-5 w-5 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          <span class="text-sm font-medium text-gray-700">
            {status ? getSessionStatusLabel(status.status) : 'Processing...'}
          </span>
        </div>
        {#if status}
          <span class="rounded-md px-2.5 py-1 text-xs font-medium {getSessionStatusClasses(status.status)}">
            {status.status}
          </span>
        {/if}
      </div>

      {#if status}
        <!-- Progress bar -->
        <div>
          <div class="mb-1.5 flex justify-between text-sm text-gray-500">
            {#if status.status === 'validating' || status.status === 'validated'}
              <span>{status.validated_files} / {status.total_files} files validated</span>
            {:else}
              <span>{status.imported_files} / {status.total_files} files imported</span>
            {/if}
            <span>{status.progress_percent.toFixed(1)}%</span>
          </div>
          <div class="h-2 overflow-hidden rounded-full bg-gray-200">
            <div
              class="h-full bg-blue-600 transition-all duration-300"
              style="width: {status.progress_percent}%"
            ></div>
          </div>
        </div>

        <!-- Invalid files warning -->
        {#if status.files.some((f) => f.status === 'invalid')}
          <div class="rounded-md border border-amber-200 bg-amber-50 p-3">
            <p class="mb-1.5 text-xs font-medium text-amber-800">Some files failed validation:</p>
            <ul class="space-y-1">
              {#each status.files.filter((f) => f.status === 'invalid') as invalidFile}
                <li class="text-xs text-amber-700">
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

  <!-- ============================================ -->
  <!-- Step: Done                                   -->
  <!-- ============================================ -->
  {#if step === 'done'}
    {@const status = $statusQuery.data}
    <div class="space-y-4">
      <div class="flex items-center gap-3 rounded-md border border-green-200 bg-green-50 p-4">
        <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-green-600 text-white">
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <div>
          <p class="font-medium text-green-800">Upload and import complete</p>
          {#if status}
            <p class="text-sm text-green-700">
              Successfully imported {status.imported_files} recording{status.imported_files !== 1 ? 's' : ''}.
            </p>
          {/if}
        </div>
      </div>

      <!-- Show any invalid files even in done state -->
      {#if status?.files.some((f) => f.status === 'invalid')}
        <div class="rounded-md border border-amber-200 bg-amber-50 p-3">
          <p class="mb-1.5 text-xs font-medium text-amber-800">
            {status.files.filter((f) => f.status === 'invalid').length} file{status.files.filter((f) => f.status === 'invalid').length !== 1 ? 's' : ''} could not be imported:
          </p>
          <ul class="space-y-1">
            {#each status.files.filter((f) => f.status === 'invalid') as invalidFile}
              <li class="text-xs text-amber-700">
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
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
        >
          Upload More Files
        </button>
      </div>
    </div>
  {/if}

  <!-- ============================================ -->
  <!-- Step: Error                                  -->
  <!-- ============================================ -->
  {#if step === 'error'}
    <div class="space-y-4">
      <div class="rounded-md border border-red-200 bg-red-50 p-4">
        <div class="mb-2 flex items-center gap-2">
          <svg class="h-4 w-4 flex-shrink-0 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span class="text-sm font-semibold text-red-700">Upload Error</span>
        </div>
        <p class="whitespace-pre-wrap break-words font-mono text-sm text-red-600">
          {errorMessage ?? 'An unknown error occurred.'}
        </p>
      </div>

      <div class="flex justify-end">
        <button
          onclick={resetToSelect}
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
        >
          Try Again
        </button>
      </div>
    </div>
  {/if}
</div>
