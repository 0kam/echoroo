<script lang="ts">
  /**
   * FileUpload - Multi-step audio file upload workflow.
   *
   * Chunk transport and retry policy live outside Svelte so that the upload
   * state can be resumed and tested independently of the UI.
   */

  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages';
  import { ApiError, apiClient } from '$lib/api/client';
  import {
    cancelUploadSession,
    chunkUrl,
    completeUploadSession,
    createUploadSession,
    fetchActiveUploadSession,
    fetchUploadSessionStatus,
    putChunk,
    sha256Hex,
    UPLOAD_CHUNK_SIZE,
  } from '$lib/api/uploads';
  import { startImport } from '$lib/api/datasets';
  import { authStore } from '$lib/stores/auth.svelte';
  import type {
    UploadSessionStatus,
    UploadSessionStatusResponse,
    CreateUploadSessionResponse,
  } from '$lib/types/data';
  import { planResume, type ResumePlan } from '$lib/upload/resume';
  import {
    DEFAULT_CONCURRENCY,
    SchedulerAbortedError,
    UploadScheduler,
    type FileUiState,
    type PlannedFile,
  } from '$lib/upload/scheduler';
  import { getLocale } from '$lib/paraglide/runtime';
  import {
    getUploadSessionStatusLabel,
    getUploadSessionStatusClass,
  } from '$lib/utils/statusFormatters';
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

  const ACCEPTED_EXTENSIONS = ['.wav', '.flac', '.mp3', '.ogg', '.opus'];
  const ACCEPTED_MIME_TYPES = [
    'audio/wav', 'audio/x-wav', 'audio/flac', 'audio/x-flac',
    'audio/mpeg', 'audio/mp3', 'audio/ogg', 'audio/opus',
  ];
  const MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024 * 1024;
  const MAX_FILE_COUNT = 500;

  type WorkflowStep =
    | 'select'
    | 'resume'
    | 'verifying'
    | 'creating'
    | 'uploading'
    | 'paused'
    | 'partial'
    | 'completing'
    | 'polling'
    | 'stalled'
    | 'done'
    | 'error';

  const STALL_HINT_MS = 30 * 1000;
  const STALL_HARD_CAP_MS = 20 * 60 * 1000;

  let step = $state<WorkflowStep>('select');
  let isDragOver = $state(false);
  let selectedFiles = $state<File[]>([]);
  let errorMessage = $state<string | null>(null);
  let resumeError = $state<string | null>(null);
  let activeSessionChecked = $state(false);

  let sessionId = $state<string | null>(null);
  let uploadPlans = $state<PlannedFile[]>([]);
  let fileStates = $state<Record<string, FileUiState>>({});
  let lastReceived = $state<Record<string, number>>({});
  let ackReceived = $state<Record<string, number>>({});
  let resumeSession = $state<UploadSessionStatusResponse | null>(null);
  let resumePlan = $state<ResumePlan | null>(null);
  let resumeUnmatched = $state<UploadSessionStatusResponse['files']>([]);
  let resumeExtra = $state<File[]>([]);
  let restartFileIds = new Set<string>();
  let currentScheduler: UploadScheduler | null = null;
  let resumeGeneration = 0;
  const onlineWaiters = new Set<() => void>();

  const totalBytes = $derived(selectedFiles.reduce((sum, file) => sum + file.size, 0));
  const isPolling = $derived(step === 'polling');
  const canImportWithoutFailed = $derived(
    uploadPlans.some((plan) => ackReceived[plan.fileId] === plan.declaredSize) ||
      (resumeSession?.files.some((file) => file.received_bytes === file.declared_size) ?? false),
  );

  const statusQuery = $derived(
    createQuery({
      queryKey: ['upload-session-status', projectId, datasetId, sessionId],
      queryFn: () => fetchUploadSessionStatus(projectId, datasetId, sessionId!),
      refetchInterval: isPolling ? 2000 : false,
      enabled: isPolling && sessionId !== null,
    }),
  );

  let importTriggered = $state(false);
  let lastStatusChangeAt = $state<number | null>(null);
  let lastStatusSignature = $state<string | null>(null);
  let nowMs = $state(Date.now());

  $effect(() => {
    if (!isPolling) return;
    const timer = setInterval(() => {
      nowMs = Date.now();
    }, 1000);
    return () => clearInterval(timer);
  });

  const pollElapsedMs = $derived(
    isPolling && lastStatusChangeAt !== null ? nowMs - lastStatusChangeAt : 0,
  );
  const showStallHint = $derived(isPolling && pollElapsedMs > STALL_HINT_MS);

  $effect(() => {
    if (typeof window === 'undefined') return;
    const notifyOnline = () => {
      for (const resolve of onlineWaiters) resolve();
      onlineWaiters.clear();
    };
    window.addEventListener('online', notifyOnline);
    return () => window.removeEventListener('online', notifyOnline);
  });

  $effect(() => {
    if (activeSessionChecked || authStore.isLoading || !apiClient.getAccessToken()) return;
    activeSessionChecked = true;
    void loadActiveSession();
  });

  $effect(() => {
    if (!isPolling) return;
    const data = $statusQuery.data;
    if (data) {
      const signature = `${data.status}:${data.validated_files}:${data.imported_files}`;
      if (signature !== lastStatusSignature) {
        lastStatusSignature = signature;
        lastStatusChangeAt = Date.now();
        nowMs = Date.now();
      }

      if (data.status === 'validated' && !importTriggered && sessionId) {
        importTriggered = true;
        startImport(projectId, datasetId, { source: `upload-session://${sessionId}` }).catch((error) => {
          step = 'error';
          errorMessage = error instanceof Error ? error.message : m.file_upload_import_start_failed();
        });
        return;
      } else if (data.status === 'imported') {
        step = 'done';
        queryClient.invalidateQueries({ queryKey: ['dataset', projectId, datasetId] });
        queryClient.invalidateQueries({ queryKey: ['import-status', projectId, datasetId] });
        onComplete?.();
        return;
      } else if (data.status === 'failed') {
        step = 'error';
        errorMessage = data.error ?? m.file_upload_import_server_failed();
        return;
      }
    }

    if (pollElapsedMs > STALL_HARD_CAP_MS) {
      step = 'stalled';
    }
  });

  $effect(() => {
    return () => {
      currentScheduler?.abort();
      resumeGeneration += 1;
    };
  });

  function isAcceptedFile(file: File): boolean {
    const lowerName = file.name.toLowerCase();
    const hasValidExt = ACCEPTED_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
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
      } else if (file.size > MAX_FILE_SIZE_BYTES) {
        errors.push(m.file_upload_exceeds_size({ name: file.name }));
      } else {
        valid.push(file);
      }
    }
    return { valid, errors };
  }

  function addFiles(incoming: File[]) {
    const { valid, errors } = validateFiles(incoming);
    errorMessage = errors.length > 0 ? errors.join('\n') : null;
    const existingNames = new Set(selectedFiles.map((file) => file.name));
    const combined = [...selectedFiles, ...valid.filter((file) => !existingNames.has(file.name))];
    if (combined.length > MAX_FILE_COUNT) {
      errorMessage = m.file_upload_max_count_exceeded({ max: MAX_FILE_COUNT });
      selectedFiles = combined.slice(0, MAX_FILE_COUNT);
    } else {
      selectedFiles = combined;
    }
  }

  function removeFile(index: number) {
    selectedFiles = selectedFiles.filter((_file, fileIndex) => fileIndex !== index);
  }

  async function loadActiveSession() {
    try {
      const active = await fetchActiveUploadSession(projectId, datasetId);
      if (active.session?.status === 'issued') {
        resumeSession = active.session;
        step = 'resume';
      } else if (active.session) {
        // Already past the transfer (uploaded / validating / validated /
        // importing): pick the session up where the previous page left it.
        // The polling effect starts the import once it is validated.
        sessionId = active.session.session_id;
        lastStatusChangeAt = Date.now();
        lastStatusSignature = null;
        nowMs = Date.now();
        step = 'polling';
      }
    } catch (error) {
      step = 'select';
      errorMessage = error instanceof Error ? error.message : m.file_upload_unexpected_error();
    }
  }

  async function chooseResumeFiles(incoming: File[]) {
    const generation = ++resumeGeneration;
    if (!resumeSession) return;
    currentScheduler?.abort();
    currentScheduler = null;
    step = 'verifying';
    const { valid, errors } = validateFiles(incoming);
    resumeError = errors.length > 0 ? errors.join('\n') : null;
    try {
      const planned = await planResume(resumeSession, valid, {
        chunkSize: UPLOAD_CHUNK_SIZE,
        hash: sha256Hex,
      });
      if (generation !== resumeGeneration) return;
      resumePlan = planned;
      resumeUnmatched = planned.unmatched;
      resumeExtra = planned.extra;
      selectedFiles = planned.matched.map((item) => item.file);
      restartFileIds = new Set(planned.needsRestart);
      sessionId = resumeSession.session_id;
      if (planned.extra.length > 0) {
        resumeError = planned.extra.map((file) => m.file_upload_resume_extra({ name: file.name })).join('\n');
      }
      if (planned.matched.length > 0) {
        // The scheduler sends into the session being resumed, not a new one.
        await runUpload(planned.matched, generation);
      } else if (planned.unmatched.length > 0) {
        step = 'partial';
      } else {
        step = 'resume';
      }
    } catch (error) {
      if (generation !== resumeGeneration) return;
      resumeError = error instanceof Error ? error.message : m.file_upload_unexpected_error();
      step = 'resume';
    }
  }

  async function addMissingFiles() {
    try {
      const active = await fetchActiveUploadSession(projectId, datasetId);
      if (!active.session) {
        step = 'error';
        errorMessage = m.file_upload_unexpected_error();
        return;
      }
      resumeGeneration += 1;
      resumeSession = active.session;
      sessionId = active.session.session_id;
      selectedFiles = [];
      resumePlan = null;
      resumeUnmatched = [];
      resumeExtra = [];
      resumeError = null;
      step = 'resume';
    } catch (error) {
      handleUploadError(error);
    }
  }

  async function startUpload() {
    if (selectedFiles.length === 0) return;
    errorMessage = null;
    step = 'creating';
    let session: CreateUploadSessionResponse;
    try {
      session = await createUploadSession(projectId, datasetId, {
        files: selectedFiles.map((file) => ({ filename: file.name, size: file.size })),
      });
    } catch (error) {
      handleUploadError(error, true);
      return;
    }
    try {
      sessionId = session.session_id;
      const plans = buildFreshPlans(session);
      restartFileIds = new Set();
      await runUpload(plans);
    } catch (error) {
      handleUploadError(error);
    }
  }

  function buildFreshPlans(session: CreateUploadSessionResponse): PlannedFile[] {
    return selectedFiles.map((file, index) => {
      const byName = session.files.filter((response) => response.original_filename === file.name);
      if (byName.length > 1) throw new Error(m.file_upload_unexpected_error());
      const response = byName[0] ?? session.files[index];
      if (!response) throw new Error(m.file_upload_unexpected_error());
      return {
        fileId: response.file_id,
        file,
        declaredSize: file.size,
        startOffset: 0,
      };
    });
  }

  async function runUpload(plans: PlannedFile[], generation?: number) {
    if (!sessionId || plans.length === 0) return;
    if (generation !== undefined && generation !== resumeGeneration) return;
    const planById = new Map(uploadPlans.map((plan) => [plan.fileId, plan]));
    for (const plan of plans) planById.set(plan.fileId, plan);
    uploadPlans = [...planById.values()];
    const activePlans = plans;
    const initialStates = { ...fileStates };
    const initialReceived = { ...lastReceived };
    const initialAcknowledged = { ...ackReceived };
    for (const plan of activePlans) {
      initialReceived[plan.fileId] = Math.max(initialReceived[plan.fileId] ?? 0, plan.startOffset);
      initialAcknowledged[plan.fileId] = plan.startOffset;
      initialStates[plan.fileId] = {
        sent: plan.startOffset,
        total: plan.declaredSize,
        state: 'queued',
      };
    }
    lastReceived = initialReceived;
    ackReceived = initialAcknowledged;
    fileStates = initialStates;
    step = 'uploading';

    const scheduler = new UploadScheduler(activePlans, {
      concurrency: DEFAULT_CONCURRENCY,
      maxAttempts: 5,
      chunkSize: UPLOAD_CHUNK_SIZE,
      backoffMs: (attempt) => Math.min(1000 * 2 ** Math.max(0, attempt - 1), 16000),
      transport: putChunk,
      refresh: () => apiClient.refreshToken(),
      currentToken: () => apiClient.getAccessToken(),
      urlFor: (fileId, offset, restart) =>
        chunkUrl(projectId, datasetId, sessionId!, fileId, offset, restart || (offset === 0 && restartFileIds.has(fileId))),
      hash: sha256Hex,
      isOnline: () => typeof navigator === 'undefined' || navigator.onLine,
      waitOnline: waitOnline,
      sleep: sleep,
    }, {
      onFileProgress: (fileId, sentBytes) => {
        const previous = lastReceived[fileId] ?? 0;
        const next = Math.max(previous, sentBytes);
        lastReceived = { ...lastReceived, [fileId]: next };
        const state = fileStates[fileId];
        if (state && state.state !== 'failed' && state.state !== 'done') {
          fileStates = { ...fileStates, [fileId]: { ...state, sent: next, state: 'sending' } };
        }
      },
      onFileAcknowledged: (fileId, received) => {
        ackReceived = { ...ackReceived, [fileId]: received };
        if (received > 0 && restartFileIds.has(fileId)) {
          const next = new Set(restartFileIds);
          next.delete(fileId);
          restartFileIds = next;
        }
      },
      onFileDone: (fileId) => {
        const state = fileStates[fileId];
        if (!state) return;
        lastReceived = { ...lastReceived, [fileId]: state.total };
        fileStates = { ...fileStates, [fileId]: { ...state, sent: state.total, state: 'done' } };
      },
      onFileFailed: (fileId, message) => {
        const state = fileStates[fileId];
        if (!state) return;
        const displayMessage = message === 'retries exhausted'
          ? m.file_upload_reason_retries({ max: 5 })
          : message === 'file unreadable'
            ? m.file_upload_reason_unreadable()
            : message;
        fileStates = { ...fileStates, [fileId]: { ...state, state: 'failed', message: displayMessage } };
      },
      onFileRetrying: (fileId, attempt, maxAttempts) => {
        const state = fileStates[fileId];
        if (!state) return;
        fileStates = { ...fileStates, [fileId]: { ...state, state: 'retrying', attempt, maxAttempts } };
      },
      onPaused: () => {
        step = 'paused';
        const nextStates = { ...fileStates };
        for (const plan of activePlans) {
          const state = nextStates[plan.fileId];
          if (state && state.state !== 'done' && state.state !== 'failed') {
            nextStates[plan.fileId] = { ...state, state: 'paused' };
          }
        }
        fileStates = nextStates;
      },
      onResumed: () => {
        step = 'uploading';
        const nextStates = { ...fileStates };
        for (const plan of activePlans) {
          const state = nextStates[plan.fileId];
          if (state?.state === 'paused') nextStates[plan.fileId] = { ...state, state: 'sending' };
        }
        fileStates = nextStates;
      },
    });

    currentScheduler = scheduler;
    try {
      await scheduler.run();
    } catch (error) {
      if (currentScheduler !== scheduler) return;
      currentScheduler = null;
      if (error instanceof SchedulerAbortedError) {
        step = 'error';
        errorMessage = error.reason === 'session' ? m.file_upload_session_lost() : m.file_upload_auth_lost();
      } else {
        handleUploadError(error);
      }
      return;
    }
    if (currentScheduler !== scheduler) return;
    currentScheduler = null;
    if (generation !== undefined && generation !== resumeGeneration) return;
    const failed = uploadPlans.filter((plan) => fileStates[plan.fileId]?.state === 'failed');
    if (failed.length > 0) {
      step = 'partial';
      return;
    }
    if (resumeUnmatched.length > 0) {
      step = 'partial';
      return;
    }
    await completeAndPoll(false);
  }

  async function retryFailed() {
    const plans = uploadPlans.filter((plan) => fileStates[plan.fileId]?.state === 'failed');
    const retryPlans = plans.map((plan) => ({
      ...plan,
      startOffset: ackReceived[plan.fileId] ?? plan.startOffset,
    }));
    await runUpload(retryPlans);
  }

  async function importWithoutFailed() {
    await completeAndPoll(true);
  }

  async function completeAndPoll(skipMissing: boolean) {
    if (!sessionId) return;
    step = 'completing';
    try {
      const response = await completeUploadSession(projectId, datasetId, sessionId, { skip_missing: skipMissing });
      if (response.status === 'issued') {
        const nextStates = { ...fileStates };
        for (const plan of uploadPlans) {
          const received = ackReceived[plan.fileId] ?? 0;
          if (received < plan.declaredSize) {
            const state = nextStates[plan.fileId];
            if (state) {
              nextStates[plan.fileId] = {
                ...state,
                state: 'failed',
                message: m.file_upload_reason_incomplete(),
              };
            }
          }
        }
        fileStates = nextStates;
        step = 'partial';
        return;
      }
      lastStatusChangeAt = Date.now();
      lastStatusSignature = null;
      nowMs = Date.now();
      importTriggered = false;
      step = 'polling';
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        (error.detail ?? error.message).includes('No files were uploaded')
      ) {
        step = 'error';
        errorMessage = m.file_upload_nothing_uploaded();
      } else {
        handleUploadError(error);
      }
    }
  }

  function handleUploadError(error: unknown, fromCreate = false) {
    step = 'error';
    if (fromCreate && error instanceof ApiError && error.status === 409) {
      errorMessage = m.file_upload_another_user();
    } else if (error instanceof ApiError && (error.status === 403 || error.status === 419)) {
      errorMessage = m.file_upload_auth_lost();
    } else {
      errorMessage = error instanceof Error ? error.message : m.file_upload_unexpected_error();
    }
  }

  function waitOnline(signal: AbortSignal): Promise<void> {
    if (typeof navigator === 'undefined' || navigator.onLine) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const resolveWaiter = () => {
        signal.removeEventListener('abort', abortWaiter);
        resolve();
      };
      const abortWaiter = () => {
        onlineWaiters.delete(resolveWaiter);
        reject(new DOMException('Aborted', 'AbortError'));
      };
      onlineWaiters.add(resolveWaiter);
      signal.addEventListener('abort', abortWaiter, { once: true });
      if (signal.aborted) abortWaiter();
    });
  }

  function retryNow() {
    for (const resolve of onlineWaiters) resolve();
    onlineWaiters.clear();
  }

  function sleep(milliseconds: number, signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
      if (signal.aborted) {
        reject(new DOMException('Aborted', 'AbortError'));
        return;
      }
      const timer = setTimeout(() => {
        signal.removeEventListener('abort', abortSleep);
        resolve();
      }, milliseconds);
      const abortSleep = () => {
        clearTimeout(timer);
        reject(new DOMException('Aborted', 'AbortError'));
      };
      signal.addEventListener('abort', abortSleep, { once: true });
    });
  }

  function getSessionStatusLabel(status: UploadSessionStatus): string {
    return getUploadSessionStatusLabel(status, {
      issued: m.upload_status_issued,
      uploaded: m.upload_status_uploaded,
      validating: m.upload_status_validating,
      validated: m.upload_status_validated,
      importing: m.upload_status_importing,
      imported: m.upload_status_imported,
      failed: m.upload_status_failed,
    });
  }

  function getSessionStatusClasses(status: UploadSessionStatus): string {
    return getUploadSessionStatusClass(status);
  }

  function overallUploadPercent(): number {
    const total = uploadPlans.reduce((sum, plan) => sum + plan.declaredSize, 0);
    if (total === 0) return uploadPlans.length === 0 ? 0 : 100;
    const sent = uploadPlans.reduce((sum, plan) => sum + (lastReceived[plan.fileId] ?? 0), 0);
    return Math.round((sent / total) * 100);
  }

  async function resetToSelect() {
    resumeGeneration += 1;
    currentScheduler?.abort();
    currentScheduler = null;
    const oldSessionId = sessionId ?? resumeSession?.session_id ?? null;
    const shouldCancel = oldSessionId !== null && !['completing', 'polling', 'done'].includes(step);
    if (shouldCancel && oldSessionId) {
      try {
        await cancelUploadSession(projectId, datasetId, oldSessionId);
      } catch {
        // Resetting the local workflow remains useful when cancellation races with expiry.
      }
    }
    step = 'select';
    selectedFiles = [];
    errorMessage = null;
    resumeError = null;
    resumeSession = null;
    resumePlan = null;
    resumeUnmatched = [];
    resumeExtra = [];
    sessionId = null;
    uploadPlans = [];
    fileStates = {};
    lastReceived = {};
    ackReceived = {};
    restartFileIds = new Set();
    importTriggered = false;
    lastStatusChangeAt = null;
    lastStatusSignature = null;
  }

  function retryPolling() {
    if (!sessionId) {
      void resetToSelect();
      return;
    }
    lastStatusChangeAt = Date.now();
    lastStatusSignature = null;
    nowMs = Date.now();
    step = 'polling';
    queryClient.invalidateQueries({
      queryKey: ['upload-session-status', projectId, datasetId, sessionId],
    });
  }
</script>

<div class="rounded-lg border border-card bg-surface-card p-6">
  <h3 class="mb-4 text-base font-semibold text-stone-900">{m.file_upload_heading()}</h3>

  {#if step === 'select'}
    <FileDropZone
      {isDragOver}
      onFilesAdded={addFiles}
      onDragOver={() => { isDragOver = true; }}
      onDragLeave={() => { isDragOver = false; }}
    />
    {#if errorMessage}
      <div class="mb-4 rounded-md border border-danger/20 bg-danger-light p-3">
        <p class="whitespace-pre-wrap text-sm text-danger">{errorMessage}</p>
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

  {#if step === 'resume'}
    {@const sentCount = resumeSession?.files.filter((file) => file.received_bytes === file.declared_size).length ?? 0}
    {@const totalCount = resumeSession?.files.length ?? 0}
    {@const remainingCount = totalCount - sentCount}
    <div class="mb-4 rounded-md border border-warning/20 bg-warning-light p-4">
      <p class="font-medium text-warning">{m.file_upload_resume_title()}</p>
      {#if resumeSession}
        <p class="mt-1 text-sm text-warning">
          {m.file_upload_resume_desc({
            started: new Date(resumeSession.created_at).toLocaleString(getLocale()),
            sent: sentCount,
            total: totalCount,
            remaining: remainingCount,
          })}
        </p>
      {/if}
      <button
        onclick={() => void resetToSelect()}
        class="mt-3 rounded-md border border-warning/30 bg-surface-card px-3 py-2 text-sm font-medium text-warning transition-colors hover:bg-warning-light"
      >
        {m.file_upload_resume_discard()}
      </button>
    </div>
    <FileDropZone
      {isDragOver}
      prompt={m.file_upload_resume_drop()}
      onFilesAdded={(files) => void chooseResumeFiles(files)}
      onDragOver={() => { isDragOver = true; }}
      onDragLeave={() => { isDragOver = false; }}
    />
    {#if resumeError}
      <p class="mb-3 whitespace-pre-wrap text-sm text-warning">{resumeError}</p>
    {/if}
    {#if resumeExtra.length > 0}
      <ul class="mb-3 space-y-1 text-sm text-warning">
        {#each resumeExtra as extra (extra.name)}
          <li>{m.file_upload_resume_extra({ name: extra.name })}</li>
        {/each}
      </ul>
    {/if}
    {#if resumePlan && resumeUnmatched.length > 0}
      <p class="text-sm text-warning">
        {m.file_upload_resume_unmatched({ count: resumeUnmatched.length })}
      </p>
    {/if}
  {/if}

  {#if step === 'verifying'}
    <div class="flex items-center gap-3">
      <svg class="h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24" aria-hidden="true">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span class="text-sm font-medium text-stone-700">{m.file_upload_verifying()}</span>
    </div>
  {/if}

  {#if step === 'creating'}
    <div class="flex items-center gap-3">
      <svg class="h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24" aria-hidden="true">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span class="text-sm font-medium text-stone-700">{m.file_upload_creating_session()}</span>
    </div>
  {/if}

  {#if step === 'uploading' || step === 'paused'}
    <UploadProgressPanel
      files={uploadPlans}
      {fileStates}
      overallPercent={overallUploadPercent()}
      paused={step === 'paused'}
    />
    {#if resumeExtra.length > 0}
      <ul class="mt-3 space-y-1 text-sm text-warning">
        {#each resumeExtra as extra (extra.name)}
          <li>{m.file_upload_resume_extra({ name: extra.name })}</li>
        {/each}
      </ul>
    {/if}
    {#if resumeUnmatched.length > 0}
      <p class="mt-3 text-sm text-warning">
        {m.file_upload_resume_unmatched({ count: resumeUnmatched.length })}
      </p>
    {/if}
    {#if step === 'paused'}
      <div class="mt-4 rounded-md border border-warning/20 bg-warning-light p-4">
        <p class="font-medium text-warning">{m.file_upload_paused_title()}</p>
        <p class="mt-1 text-sm text-warning">{m.file_upload_paused_desc()}</p>
        <button
          onclick={retryNow}
          class="mt-3 rounded-md bg-warning px-3 py-2 text-sm font-medium text-white transition-colors hover:opacity-90"
        >
          {m.file_upload_retry_now()}
        </button>
      </div>
    {/if}
  {/if}

  {#if step === 'partial'}
    {@const failedPlans = uploadPlans.filter((plan) => fileStates[plan.fileId]?.state === 'failed')}
    {@const sentCount = uploadPlans.filter((plan) => fileStates[plan.fileId]?.state === 'done').length}
    <div class="space-y-4">
      <div class="rounded-md border border-warning/20 bg-warning-light p-4">
        <p class="font-medium text-warning">{m.file_upload_partial_title({ failed: failedPlans.length })}</p>
        <p class="mt-1 text-sm text-warning">{m.file_upload_partial_desc({ sent: sentCount })}</p>
      </div>
      <ul class="divide-y divide-stone-100 rounded-md border border-stone-200">
        {#each failedPlans as plan (plan.fileId)}
          <li class="px-3 py-2 text-sm">
            <p class="font-medium text-stone-700">{plan.file.name}</p>
            <p class="text-xs text-danger">{fileStates[plan.fileId]?.message}</p>
          </li>
          {/each}
          {#each resumeUnmatched as unmatched (unmatched.file_id)}
            <li class="px-3 py-2 text-sm">
              <p class="font-medium text-stone-700">{unmatched.original_filename}</p>
              <p class="text-xs text-warning">{m.file_upload_reason_not_selected()}</p>
            </li>
          {/each}
        </ul>
      <div class="flex flex-wrap justify-end gap-2">
        <button
          onclick={() => void retryFailed()}
          class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700"
        >
          {m.file_upload_retry_failed({ count: failedPlans.length })}
        </button>
        <button
          onclick={() => void importWithoutFailed()}
          disabled={!canImportWithoutFailed}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-surface-card"
        >
          {m.file_upload_import_without_failed({ count: failedPlans.length })}
        </button>
        {#if resumeUnmatched.length > 0}
          <button
            onclick={() => void addMissingFiles()}
            class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700"
          >
            {m.file_upload_add_missing()}
          </button>
        {/if}
      </div>
    </div>
  {/if}

  {#if step === 'completing'}
    <div class="flex items-center gap-3">
      <svg class="h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24" aria-hidden="true">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span class="text-sm font-medium text-stone-700">{m.file_upload_finalizing()}</span>
    </div>
  {/if}

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
            <div class="h-full bg-primary-600 transition-all duration-300" style="width: {status.progress_percent}%"></div>
          </div>
        </div>

        {#if status.files.some((file) => file.status === 'invalid')}
          <div class="rounded-md border border-warning/20 bg-warning-light p-3">
            <p class="mb-1.5 text-xs font-medium text-warning">{m.file_upload_validation_warning()}</p>
            <ul class="space-y-1">
              {#each status.files.filter((file) => file.status === 'invalid') as invalidFile}
                <li class="text-xs text-warning">
                  <span class="font-medium">{invalidFile.original_filename}</span>
                  {#if invalidFile.validation_error}&mdash; {invalidFile.validation_error}{/if}
                </li>
              {/each}
            </ul>
          </div>
        {/if}
        {#if status.files.some((file) => file.status === 'skipped')}
          <div class="rounded-md border border-stone-200 bg-stone-50 p-3">
            <p class="mb-1.5 text-xs font-medium text-stone-600">{m.file_upload_skipped_files()}</p>
            <ul class="space-y-1">
              {#each status.files.filter((file) => file.status === 'skipped') as skippedFile}
                <li class="text-xs text-stone-600">
                  <span class="font-medium">{skippedFile.original_filename}</span>
                  <span> ({m.file_upload_skipped_label()})</span>
                </li>
              {/each}
            </ul>
          </div>
        {/if}
      {/if}
      {#if showStallHint}<p class="text-xs text-warning">{m.file_upload_stall_hint()}</p>{/if}
    </div>
  {/if}

  {#if step === 'stalled'}
    <div class="space-y-4">
      <div class="rounded-md border border-danger/20 bg-danger-light p-4">
        <p class="text-sm font-semibold text-danger">{m.file_upload_stalled_title()}</p>
        <p class="mt-2 text-sm text-danger">
          {m.file_upload_stalled_desc({ minutes: Math.round(STALL_HARD_CAP_MS / 60000) })}
        </p>
      </div>
      <div class="flex justify-end gap-2">
        <button onclick={() => void resetToSelect()} class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50">
          {m.file_upload_start_over()}
        </button>
        <button onclick={retryPolling} class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700">
          {m.file_upload_recheck()}
        </button>
      </div>
    </div>
  {/if}

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
          {#if status}<p class="text-sm text-success">{m.file_upload_success({ count: status.imported_files })}</p>{/if}
        </div>
      </div>
      {#if status?.files.some((file) => file.status === 'invalid')}
        <div class="rounded-md border border-warning/20 bg-warning-light p-3">
          <p class="mb-1.5 text-xs font-medium text-warning">
            {m.file_upload_import_warning({ count: status.files.filter((file) => file.status === 'invalid').length })}
          </p>
          <ul class="space-y-1">
            {#each status.files.filter((file) => file.status === 'invalid') as invalidFile}
              <li class="text-xs text-warning"><span class="font-medium">{invalidFile.original_filename}</span>{#if invalidFile.validation_error}&mdash; {invalidFile.validation_error}{/if}</li>
            {/each}
          </ul>
        </div>
      {/if}
      {#if status?.files.some((file) => file.status === 'skipped')}
        <div class="rounded-md border border-stone-200 bg-stone-50 p-3">
          <p class="mb-1.5 text-xs font-medium text-stone-600">{m.file_upload_skipped_files()}</p>
          <ul class="space-y-1">
            {#each status.files.filter((file) => file.status === 'skipped') as skippedFile}
              <li class="text-xs text-stone-600"><span class="font-medium">{skippedFile.original_filename}</span> ({m.file_upload_skipped_label()})</li>
            {/each}
          </ul>
        </div>
      {/if}
      <div class="flex justify-end">
        <button onclick={() => void resetToSelect()} class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50">
          {m.file_upload_more()}
        </button>
      </div>
    </div>
  {/if}

  {#if step === 'error'}
    <div class="space-y-4">
      <div class="rounded-md border border-danger/20 bg-danger-light p-4">
        <p class="text-sm font-semibold text-danger">{m.file_upload_error()}</p>
        <p class="mt-2 whitespace-pre-wrap break-words font-mono text-sm text-danger">{errorMessage ?? m.file_upload_unknown_error()}</p>
      </div>
      <div class="flex justify-end">
        <button onclick={() => void resetToSelect()} class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50">
          {m.file_upload_try_again()}
        </button>
      </div>
    </div>
  {/if}
</div>
