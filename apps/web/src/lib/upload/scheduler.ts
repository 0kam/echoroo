import type { ChunkResult, PutChunkOptions } from '$lib/api/uploads';

export const DEFAULT_CONCURRENCY = 3;

export interface PlannedFile {
  fileId: string;
  file: File;
  declaredSize: number;
  startOffset: number;
}

export interface FileUiState {
  sent: number;
  total: number;
  state: 'queued' | 'sending' | 'retrying' | 'done' | 'failed' | 'paused';
  attempt?: number;
  maxAttempts?: number;
  message?: string;
}

export interface SchedulerCallbacks {
  onFileProgress(fileId: string, sentBytes: number): void;
  onFileAcknowledged(fileId: string, received: number): void;
  onFileDone(fileId: string): void;
  onFileFailed(fileId: string, message: string): void;
  onFileRetrying(fileId: string, attempt: number, maxAttempts: number): void;
  onPaused(reason: 'offline' | 'stall'): void;
  onResumed(): void;
}

export interface SchedulerOptions {
  concurrency: number;
  maxAttempts: number;
  chunkSize: number;
  backoffMs: (attempt: number) => number;
  transport: (url: string, body: Blob, opts: PutChunkOptions) => Promise<ChunkResult>;
  refresh: () => Promise<void>;
  currentToken: () => string | null;
  urlFor: (fileId: string, offset: number, restart: boolean) => string;
  hash: (data: ArrayBuffer) => Promise<string | null>;
  isOnline: () => boolean;
  waitOnline: (signal: AbortSignal) => Promise<void>;
  sleep: (ms: number, signal: AbortSignal) => Promise<void>;
}

export class SchedulerAbortedError extends Error {
  constructor(
    public readonly reason: 'session' | 'auth',
    message: string,
  ) {
    super(message);
    this.name = 'SchedulerAbortedError';
  }
}

interface FileProgress {
  plan: PlannedFile;
  offset: number;
  reportedOffset: number;
  outcome: 'pending' | 'done' | 'failed';
}

function defaultBackoff(attempt: number): number {
  return Math.min(1000 * 2 ** Math.max(0, attempt - 1), 16000);
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

async function readBlob(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === 'function') return blob.arrayBuffer();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error ?? new Error('Unable to read file'));
    reader.readAsArrayBuffer(blob);
  });
}

export class UploadScheduler {
  private readonly controller = new AbortController();
  private readonly progress: FileProgress[];
  private refreshPromise: Promise<void> | null = null;
  private fatalError: SchedulerAbortedError | null = null;
  private runPromise: Promise<{ done: string[]; failed: string[] }> | null = null;
  private userAborted = false;

  constructor(
    files: PlannedFile[],
    private readonly opts: SchedulerOptions,
    private readonly cb: SchedulerCallbacks,
  ) {
    this.progress = files.map((plan) => ({
      plan,
      offset: plan.startOffset,
      reportedOffset: plan.startOffset,
      outcome: 'pending',
    }));
  }

  run(): Promise<{ done: string[]; failed: string[] }> {
    if (this.runPromise) return this.runPromise;
    this.runPromise = this.runInternal();
    return this.runPromise;
  }

  abort(): void {
    if (this.controller.signal.aborted) return;
    this.userAborted = true;
    this.controller.abort();
  }

  private async runInternal(): Promise<{ done: string[]; failed: string[] }> {
    const concurrency = Math.max(1, Math.floor(this.opts.concurrency) || DEFAULT_CONCURRENCY);
    let nextIndex = 0;

    const worker = async () => {
      while (!this.controller.signal.aborted) {
        const index = nextIndex++;
        const item = this.progress[index];
        if (!item) return;
        await this.processFile(item);
      }
    };

    const workers = Array.from(
      { length: Math.min(concurrency, this.progress.length) },
      () => worker(),
    );
    await Promise.all(workers);

    if (this.fatalError) throw this.fatalError;

    return {
      done: this.progress.filter((item) => item.outcome === 'done').map((item) => item.plan.fileId),
      failed: this.progress.filter((item) => item.outcome === 'failed').map((item) => item.plan.fileId),
    };
  }

  private async processFile(item: FileProgress): Promise<void> {
    const { plan } = item;

    if (item.offset >= plan.declaredSize) {
      this.markDone(item);
      return;
    }

    this.reportProgress(item, item.offset);

    while (!this.controller.signal.aborted && item.offset < plan.declaredSize) {
      if (!(await this.pauseIfOffline())) return;

      const chunkStart = item.offset;
      const chunkEnd = Math.min(chunkStart + this.opts.chunkSize, plan.declaredSize);
      const body = plan.file.slice(chunkStart, chunkEnd);
      let hash: string | null;
      try {
        hash = await this.opts.hash(await readBlob(body));
      } catch {
        this.markFailed(item, 'file unreadable');
        return;
      }

      let attempt = 0;
      let refreshed = false;
      while (!this.controller.signal.aborted) {
        const restart = false;
        this.reportProgress(item, item.offset);

        let result: ChunkResult;
        try {
          result = await this.abortable(
            Promise.resolve().then(() =>
              this.opts.transport(this.opts.urlFor(plan.fileId, chunkStart, restart), body, {
                sha256: hash,
                signal: this.controller.signal,
                onProgress: (loadedBytes) => {
                  this.reportProgress(item, chunkStart + loadedBytes);
                },
              }),
            ),
          );
        } catch (error) {
          if (isAbortError(error) || this.controller.signal.aborted) return;
          this.markFailed(item, 'network error');
          return;
        }

        if (result.kind === 'ok') {
          item.offset = result.received;
          this.cb.onFileAcknowledged(plan.fileId, result.received);
          this.reportProgress(item, item.offset);
          if (result.complete || item.offset >= plan.declaredSize) {
            this.markDone(item);
            return;
          }
          break;
        }

        if (result.kind === 'offset') {
          item.offset = result.received;
          this.cb.onFileAcknowledged(plan.fileId, result.received);
          this.reportProgress(item, item.offset);
          break;
        }

        if (result.kind === 'fatal') {
          if (result.reason === 'file') {
            this.markFailed(item, result.message);
          } else {
            this.abortForFatal(result.reason, result.message);
          }
          return;
        }

        if (result.kind === 'unauthorized') {
          if (result.tokenUsed !== this.opts.currentToken()) {
            continue;
          }
          if (refreshed) {
            this.abortForFatal('auth', 'Token refresh did not restore the upload session.');
            return;
          }
          refreshed = true;
          try {
            await this.sharedRefresh();
          } catch (error) {
            const message = error instanceof Error ? error.message : 'Token refresh failed.';
            this.abortForFatal('auth', message);
            return;
          }
          continue;
        }

        attempt += 1;
        if (result.kind === 'network') {
          this.cb.onFileRetrying(plan.fileId, attempt, this.opts.maxAttempts);
        } else {
          this.cb.onFileRetrying(plan.fileId, attempt, this.opts.maxAttempts);
        }
        if (attempt >= this.opts.maxAttempts) {
          this.markFailed(item, 'retries exhausted');
          return;
        }

        const delay = result.kind === 'retry'
          ? result.after * 1000
          : (this.opts.backoffMs ?? defaultBackoff)(attempt);
        try {
          await this.abortable(this.opts.sleep(delay, this.controller.signal));
        } catch (error) {
          if (isAbortError(error) || this.controller.signal.aborted) return;
          this.markFailed(item, 'network error');
          return;
        }
        if (!(await this.pauseIfOffline())) return;
        refreshed = false;
      }
    }

    if (!this.controller.signal.aborted && item.offset >= plan.declaredSize) {
      this.markDone(item);
    }
  }

  private async pauseIfOffline(): Promise<boolean> {
    if (this.opts.isOnline()) return true;
    if (this.controller.signal.aborted) return false;
    this.cb.onPaused('offline');
    try {
      await this.abortable(this.opts.waitOnline(this.controller.signal));
    } catch (error) {
      if (isAbortError(error) || this.controller.signal.aborted) return false;
      throw error;
    }
    if (!this.controller.signal.aborted) this.cb.onResumed();
    return !this.controller.signal.aborted;
  }

  private sharedRefresh(): Promise<void> {
    if (!this.refreshPromise) {
      this.refreshPromise = this.opts.refresh().finally(() => {
        this.refreshPromise = null;
      });
    }
    return this.refreshPromise;
  }

  private markDone(item: FileProgress): void {
    if (item.outcome !== 'pending') return;
    item.offset = item.plan.declaredSize;
    item.outcome = 'done';
    this.reportProgress(item, item.offset);
    this.cb.onFileDone(item.plan.fileId);
  }

  private reportProgress(item: FileProgress, sentBytes: number): void {
    item.reportedOffset = Math.max(item.reportedOffset, sentBytes);
    this.cb.onFileProgress(item.plan.fileId, item.reportedOffset);
  }

  private markFailed(item: FileProgress, message: string): void {
    if (item.outcome !== 'pending') return;
    item.outcome = 'failed';
    this.cb.onFileFailed(item.plan.fileId, message);
  }

  private abortForFatal(reason: 'session' | 'auth', message: string): void {
    if (this.fatalError || this.userAborted) return;
    this.fatalError = new SchedulerAbortedError(reason, message);
    this.controller.abort();
  }

  private abortable<T>(promise: Promise<T>): Promise<T> {
    if (this.controller.signal.aborted) {
      return Promise.reject(new DOMException('Aborted', 'AbortError'));
    }
    return new Promise<T>((resolve, reject) => {
      const onAbort = () => reject(new DOMException('Aborted', 'AbortError'));
      this.controller.signal.addEventListener('abort', onAbort, { once: true });
      promise.then(
        (value) => {
          this.controller.signal.removeEventListener('abort', onAbort);
          resolve(value);
        },
        (error: unknown) => {
          this.controller.signal.removeEventListener('abort', onAbort);
          reject(error);
        },
      );
    });
  }
}
