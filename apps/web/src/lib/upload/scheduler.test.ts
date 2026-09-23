import { describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_CONCURRENCY,
  SchedulerAbortedError,
  UploadScheduler,
  type PlannedFile,
  type SchedulerCallbacks,
  type SchedulerOptions,
} from './scheduler';
import type { ChunkResult } from '$lib/api/uploads';

function planned(fileId: string, size = 3, startOffset = 0): PlannedFile {
  return { fileId, file: new File([new Uint8Array(size)], `${fileId}.wav`), declaredSize: size, startOffset };
}

function callbacks(overrides: Partial<SchedulerCallbacks> = {}): SchedulerCallbacks {
  return {
    onFileProgress: vi.fn(),
    onFileAcknowledged: vi.fn(),
    onFileDone: vi.fn(),
    onFileFailed: vi.fn(),
    onFileRetrying: vi.fn(),
    onPaused: vi.fn(),
    onResumed: vi.fn(),
    ...overrides,
  };
}

function options(transport: SchedulerOptions['transport'], overrides: Partial<SchedulerOptions> = {}): SchedulerOptions {
  return {
    concurrency: DEFAULT_CONCURRENCY,
    maxAttempts: 5,
    chunkSize: 1,
    backoffMs: vi.fn((attempt) => attempt * 10),
    transport,
    refresh: vi.fn(async () => undefined),
    currentToken: () => 'A',
    urlFor: vi.fn((fileId, offset, restart) => `${fileId}:${offset}:${restart}`),
    hash: vi.fn(async () => null),
    isOnline: () => true,
    waitOnline: vi.fn(async () => undefined),
    sleep: vi.fn(async () => undefined),
    ...overrides,
  };
}

function scriptedTransport(results: Record<string, ChunkResult[]>): SchedulerOptions['transport'] {
  return vi.fn(async (url) => {
    const fileId = url.split(':')[0] ?? '';
    const result = results[fileId]?.shift();
    if (!result) throw new Error(`missing result for ${fileId}`);
    return result;
  });
}

function blobSize(body: Blob): number {
  return body.size;
}

describe('UploadScheduler', () => {
  it('uploads multiple files one chunk at a time and reports monotonic progress', async () => {
    const transport = scriptedTransport({
      a: [
        { kind: 'ok', received: 1, complete: false },
        { kind: 'ok', received: 2, complete: false },
        { kind: 'ok', received: 3, complete: true },
      ],
      b: [
        { kind: 'ok', received: 1, complete: false },
        { kind: 'ok', received: 2, complete: false },
        { kind: 'ok', received: 3, complete: true },
      ],
    });
    const progress = new Map<string, number[]>();
    const cb = callbacks({
      onFileProgress: (id, sent) => progress.set(id, [...(progress.get(id) ?? []), sent]),
    });
    const result = await new UploadScheduler([planned('a'), planned('b')], options(transport), cb).run();
    expect(result).toEqual({ done: ['a', 'b'], failed: [] });
    for (const values of progress.values()) {
      expect(values).toEqual([...values].sort((left, right) => left - right));
    }
    expect(cb.onFileDone).toHaveBeenCalledTimes(2);
  });

  it('resynchronizes an offset conflict without consuming a retry', async () => {
    const bodies: number[] = [];
    const transport = vi.fn(async (_url, body) => {
      bodies.push(blobSize(body));
      return bodies.length === 1
        ? { kind: 'offset', received: 1 } as const
        : { kind: 'ok', received: 3, complete: true } as const;
    });
    const result = await new UploadScheduler([planned('a')], options(transport), callbacks()).run();
    expect(result.done).toEqual(['a']);
    expect(bodies).toEqual([1, 1]);
  });

  it('labels accepted acknowledgements separately from offset conflicts', async () => {
    const acknowledged = vi.fn();
    const transport = scriptedTransport({
      a: [
        { kind: 'ok', received: 1, complete: false },
        { kind: 'offset', received: 2 },
        { kind: 'ok', received: 3, complete: true },
      ],
    });
    const cb = callbacks({ onFileAcknowledged: acknowledged });

    await new UploadScheduler([planned('a')], options(transport), cb).run();

    expect(acknowledged).toHaveBeenNthCalledWith(1, 'a', 1, 'ok');
    expect(acknowledged).toHaveBeenNthCalledWith(2, 'a', 2, 'offset');
    expect(acknowledged).toHaveBeenNthCalledWith(3, 'a', 3, 'ok');
  });

  it('retries network errors and lets another file finish after one file gives up', async () => {
    const retrying = vi.fn();
    const transport = scriptedTransport({
      bad: Array.from({ length: 5 }, () => ({ kind: 'network' })),
      good: [{ kind: 'ok', received: 1, complete: true }],
    });
    const sleep = vi.fn(async () => undefined);
    const cb = callbacks({ onFileRetrying: retrying });
    const result = await new UploadScheduler(
      [planned('bad', 1), planned('good', 1)],
      options(transport, { concurrency: 2, sleep }),
      cb,
    ).run();
    expect(result).toEqual({ done: ['good'], failed: ['bad'] });
    expect(retrying).toHaveBeenCalledTimes(5);
    expect(sleep).toHaveBeenCalledTimes(4);
    expect(cb.onFileFailed).toHaveBeenCalledWith('bad', 'retries exhausted');
  });

  it('honours Retry-After delays', async () => {
    const sleep = vi.fn(async () => undefined);
    const transport = scriptedTransport({
      a: [
        { kind: 'retry', after: 3 },
        { kind: 'ok', received: 1, complete: true },
      ],
    });
    await new UploadScheduler([planned('a', 1)], options(transport, { sleep }), callbacks()).run();
    expect(sleep).toHaveBeenCalledWith(3000, expect.any(AbortSignal));
  });

  it('shares one refresh across concurrent unauthorized responses', async () => {
    let refreshRelease: () => void = () => undefined;
    const refreshGate = new Promise<void>((resolve) => { refreshRelease = resolve; });
    const refresh = vi.fn(() => refreshGate);
    const counts = new Map<string, number>();
    const transport = vi.fn(async (url) => {
      const id = url.split(':')[0] ?? '';
      const count = (counts.get(id) ?? 0) + 1;
      counts.set(id, count);
      return count === 1
        ? { kind: 'unauthorized', tokenUsed: 'A' } as const
        : { kind: 'ok', received: 1, complete: true } as const;
    });
    const run = new UploadScheduler(
      [planned('a', 1), planned('b', 1)],
      options(transport, { concurrency: 2, refresh }),
      callbacks(),
    ).run();
    // Both files hit 401 after several async hops (slice → arrayBuffer → hash →
    // transport); wait for the shared refresh instead of assuming one tick.
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(transport).toHaveBeenCalledTimes(2));
    expect(refresh).toHaveBeenCalledTimes(1);
    refreshRelease();
    await expect(run).resolves.toEqual({ done: ['a', 'b'], failed: [] });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('does not refresh again for a late 401 sent with an old token', async () => {
    let currentToken = 'A';
    let releaseLate401: () => void = () => undefined;
    const late401 = new Promise<void>((resolve) => { releaseLate401 = resolve; });
    const refresh = vi.fn(async () => {
      currentToken = 'B';
      releaseLate401();
    });
    const counts = new Map<string, number>();
    const transport = vi.fn(async (url) => {
      const id = url.split(':')[0] ?? '';
      const count = (counts.get(id) ?? 0) + 1;
      counts.set(id, count);
      if (count === 1 && id === 'b') await late401;
      return count === 1
        ? { kind: 'unauthorized', tokenUsed: 'A' } as const
        : { kind: 'ok', received: 1, complete: true } as const;
    });
    const run = new UploadScheduler(
      [planned('a', 1), planned('b', 1)],
      options(transport, { concurrency: 2, refresh, currentToken: () => currentToken }),
      callbacks(),
    ).run();

    await expect(run).resolves.toEqual({ done: ['a', 'b'], failed: [] });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('pauses offline work until online', async () => {
    let online = false;
    let releaseOnline: () => void = () => undefined;
    const onlineGate = new Promise<void>((resolve) => { releaseOnline = resolve; });
    const paused = vi.fn();
    const resumed = vi.fn();
    const transport = scriptedTransport({ a: [{ kind: 'ok', received: 1, complete: true }] });
    const run = new UploadScheduler(
      [planned('a', 1)],
      options(transport, { isOnline: () => online, waitOnline: () => onlineGate }),
      callbacks({ onPaused: paused, onResumed: resumed }),
    ).run();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(transport).not.toHaveBeenCalled();
    expect(paused).toHaveBeenCalledWith('offline');
    online = true;
    releaseOnline();
    await expect(run).resolves.toEqual({ done: ['a'], failed: [] });
    expect(resumed).toHaveBeenCalledTimes(1);
  });

  it('aborts the run on a fatal session result', async () => {
    const transport = scriptedTransport({
      a: [{ kind: 'fatal', reason: 'session', message: 'closed' }],
      b: [{ kind: 'ok', received: 1, complete: true }],
    });
    const scheduler = new UploadScheduler([planned('a', 1), planned('b', 1)], options(transport), callbacks());
    await expect(scheduler.run()).rejects.toMatchObject({
      name: 'SchedulerAbortedError',
      reason: 'session',
      message: 'closed',
    } satisfies Partial<SchedulerAbortedError>);
  });

  it('cancels in-flight work and resolves when aborted', async () => {
    const transport = vi.fn(() => new Promise<ChunkResult>(() => undefined));
    const scheduler = new UploadScheduler([planned('a')], options(transport), callbacks());
    const run = scheduler.run();
    await new Promise((resolve) => setTimeout(resolve, 0));
    scheduler.abort();
    await expect(run).resolves.toEqual({ done: [], failed: [] });
  });

  it('resolves promptly when aborted during backoff', async () => {
    const sleep = vi.fn((_milliseconds: number, signal: AbortSignal) => new Promise<void>((resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    }));
    const transport = scriptedTransport({ a: [{ kind: 'network' }] });
    const scheduler = new UploadScheduler([planned('a', 1)], options(transport, { sleep }), callbacks());
    const run = scheduler.run();

    await vi.waitFor(() => expect(sleep).toHaveBeenCalledTimes(1));
    scheduler.abort();
    await expect(run).resolves.toEqual({ done: [], failed: [] });
  });

  it('reports a file already received without sending a request', async () => {
    const transport = vi.fn();
    const cb = callbacks();
    const result = await new UploadScheduler([planned('a', 3, 3)], options(transport), cb).run();
    expect(result).toEqual({ done: ['a'], failed: [] });
    expect(transport).not.toHaveBeenCalled();
    expect(cb.onFileDone).toHaveBeenCalledWith('a');
  });

  it('never has more than three unresolved chunks', async () => {
    let active = 0;
    let maximum = 0;
    const transport = vi.fn(async () => {
      active += 1;
      maximum = Math.max(maximum, active);
      await Promise.resolve();
      active -= 1;
      return { kind: 'ok', received: 1, complete: true } as const;
    });
    await new UploadScheduler(
      [planned('a', 1), planned('b', 1), planned('c', 1), planned('d', 1)],
      options(transport),
      callbacks(),
    ).run();
    expect(maximum).toBeLessThanOrEqual(3);
  });
});
