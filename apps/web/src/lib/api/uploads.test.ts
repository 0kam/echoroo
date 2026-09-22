import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from './client';
import { putChunk } from './uploads';

type Listener = (event?: ProgressEvent) => void;

class FakeUpload {
  private readonly listeners = new Map<string, Listener[]>();

  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  emit(type: string, event?: ProgressEvent) {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

class FakeXMLHttpRequest {
  static next = { status: 200, responseText: '{"received_bytes": 3, "complete": true}', headers: {} as Record<string, string> };
  static last: FakeXMLHttpRequest | null = null;

  readonly upload = new FakeUpload();
  readonly headers: Record<string, string> = {};
  private readonly listeners = new Map<string, Listener[]>();
  status = 0;
  responseText = '';
  withCredentials = false;
  url = '';
  body: Blob | null = null;

  constructor() {
    FakeXMLHttpRequest.last = this;
  }

  open(_method: string, url: string) {
    this.url = url;
  }

  send(body: Blob) {
    this.body = body;
    const response = FakeXMLHttpRequest.next;
    this.status = response.status;
    this.responseText = response.responseText;
    queueMicrotask(() => this.emit('load'));
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  abort() {
    this.status = 0;
    this.emit('abort');
  }

  getResponseHeader(name: string) {
    return FakeXMLHttpRequest.next.headers[name] ?? null;
  }

  emit(type: string, event?: ProgressEvent) {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

const xhrConstructor = globalThis.XMLHttpRequest;

describe('putChunk', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    apiClient.setAccessToken('access-token');
    document.cookie = 'echoroo_csrf=csrf-token; path=/';
    FakeXMLHttpRequest.next = {
      status: 200,
      responseText: '{"received_bytes": 3, "complete": true}',
      headers: {},
    };
    globalThis.XMLHttpRequest = FakeXMLHttpRequest as unknown as typeof XMLHttpRequest;
  });

  afterEach(() => {
    globalThis.XMLHttpRequest = xhrConstructor;
  });

  function callChunk() {
    return putChunk('/chunk', new Blob(['abc']), {
      sha256: 'digest',
      signal: new AbortController().signal,
    });
  }

  it('maps an accepted response and sends upload headers', async () => {
    await expect(callChunk()).resolves.toEqual({ kind: 'ok', received: 3, complete: true });
    expect(FakeXMLHttpRequest.last?.withCredentials).toBe(true);
    expect(FakeXMLHttpRequest.last?.headers).toEqual({
      Authorization: 'Bearer access-token',
      'X-CSRF-Token': 'csrf-token',
      'X-Chunk-SHA256': 'digest',
    });
  });

  it('maps offset conflicts, session conflicts, and retry-after responses', async () => {
    FakeXMLHttpRequest.next = { status: 409, responseText: '{"detail":{"received_bytes":2}}', headers: {} };
    await expect(callChunk()).resolves.toEqual({ kind: 'offset', received: 2 });

    FakeXMLHttpRequest.next = { status: 409, responseText: '{"detail":"session closed"}', headers: {} };
    await expect(callChunk()).resolves.toEqual({ kind: 'fatal', reason: 'session', message: 'session closed' });

    FakeXMLHttpRequest.next = { status: 429, responseText: '', headers: { 'Retry-After': '4' } };
    await expect(callChunk()).resolves.toEqual({ kind: 'retry', after: 4 });
  });

  it('maps auth, file, and network failures', async () => {
    FakeXMLHttpRequest.next = { status: 401, responseText: '', headers: {} };
    await expect(callChunk()).resolves.toEqual({ kind: 'unauthorized' });

    FakeXMLHttpRequest.next = { status: 403, responseText: '{"detail":"csrf"}', headers: {} };
    await expect(callChunk()).resolves.toEqual({ kind: 'fatal', reason: 'auth', message: 'csrf' });

    FakeXMLHttpRequest.next = { status: 413, responseText: 'too large', headers: {} };
    await expect(callChunk()).resolves.toEqual({ kind: 'fatal', reason: 'file', message: 'too large' });

    FakeXMLHttpRequest.next = { status: 0, responseText: '', headers: {} };
    const promise = callChunk();
    FakeXMLHttpRequest.last?.emit('error');
    await expect(promise).resolves.toEqual({ kind: 'network' });
  });

  it('rejects with AbortError when the signal aborts', async () => {
    const controller = new AbortController();
    const promise = putChunk('/chunk', new Blob(['abc']), {
      sha256: null,
      signal: controller.signal,
    });
    controller.abort();
    await expect(promise).rejects.toMatchObject({ name: 'AbortError' });
  });
});
