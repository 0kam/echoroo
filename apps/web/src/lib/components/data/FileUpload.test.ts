import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ComponentProps } from 'svelte';

vi.mock('svelte', async () => {
  // @ts-expect-error Svelte does not publish declarations for this runtime path.
  return await import('../../../../node_modules/svelte/src/index-client.js');
});

const mockedUploads = vi.hoisted(() => ({
  cancelUploadSession: vi.fn(),
  chunkUrl: vi.fn(() => '/chunk'),
  completeUploadSession: vi.fn(),
  createUploadSession: vi.fn(),
  fetchActiveUploadSession: vi.fn(),
  fetchUploadSessionStatus: vi.fn(),
  putChunk: vi.fn(),
  sha256Hex: vi.fn(async () => null),
  UPLOAD_CHUNK_SIZE: 8 * 1024 * 1024,
}));
const mockedScheduler = vi.hoisted(() => ({
  instanceCount: 0,
  runImpl: null as null | ((fileId: string | undefined, cb: {
    onFileAcknowledged?: (fileId: string, received: number) => void;
    onFileDone: (fileId: string) => void;
  }) => Promise<{ done: string[]; failed: string[] }>),
}));
const { fetchActiveUploadSession, createUploadSession, completeUploadSession, cancelUploadSession } = mockedUploads;

vi.mock('$lib/api/uploads', () => mockedUploads);
vi.mock('$lib/api/datasets', () => ({ startImport: vi.fn() }));
vi.mock('@tanstack/svelte-query', () => ({
  createQuery: () => ({
    subscribe(run: (value: { data: undefined }) => void) {
      run({ data: undefined });
      return () => undefined;
    },
  }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock('$lib/upload/scheduler', () => ({
  DEFAULT_CONCURRENCY: 3,
  SchedulerAbortedError: class SchedulerAbortedError extends Error {},
  UploadScheduler: class UploadScheduler {
    constructor(private readonly files: Array<{ fileId: string }>, private readonly _opts: unknown, private readonly cb: {
      onFileAcknowledged?: (fileId: string, received: number) => void;
      onFileDone: (fileId: string) => void;
      onFileFailed: (fileId: string, message: string) => void;
    }) {
      mockedScheduler.instanceCount += 1;
    }
    run() {
      const fileId = this.files[0]?.fileId;
      if (mockedScheduler.runImpl) return mockedScheduler.runImpl(fileId, this.cb);
      const file = this.files[0];
      if (file) this.cb.onFileFailed(file.fileId, 'network failed');
      return Promise.resolve({ done: [], failed: file ? [file.fileId] : [] });
    }
    abort() {}
  },
}));

import { mount, tick, unmount } from 'svelte';
import { apiClient } from '$lib/api/client';
import { authStore } from '$lib/stores/auth.svelte';
import FileUpload from './FileUpload.svelte';

type MountedComponent = ReturnType<typeof mount>;
let component: MountedComponent | null = null;

const issuedSession = {
  session_id: 'session-1',
  status: 'issued' as const,
  total_files: 1,
  total_bytes: 3,
  validated_files: 0,
  imported_files: 0,
  progress_percent: 0,
  error: null,
  created_at: '2026-09-23T00:00:00Z',
  updated_at: '2026-09-23T00:00:00Z',
  files: [{
    file_id: 'file-1',
    original_filename: 'bird.wav',
    declared_size: 3,
    received_bytes: 0,
    chunk_digests: [],
    status: 'pending' as const,
    file_size: 3,
    duration: null,
    samplerate: null,
    channels: null,
    validation_error: null,
    recording_id: null,
  }],
};

async function render(props: ComponentProps<typeof FileUpload> = { projectId: 'p', datasetId: 'd' }) {
  const target = document.createElement('div');
  document.body.appendChild(target);
  component = mount(FileUpload, { target, props });
  await tick();
  await Promise.resolve();
  await tick();
  return target;
}

afterEach(async () => {
  if (component) {
    await unmount(component);
    component = null;
  }
  document.body.innerHTML = '';
  vi.clearAllMocks();
  mockedScheduler.instanceCount = 0;
  mockedScheduler.runImpl = null;
});

beforeEach(() => {
  apiClient.setAccessToken('test-token');
  authStore.setLoading(false);
  fetchActiveUploadSession.mockResolvedValue({ session: issuedSession });
  completeUploadSession.mockReset();
});

describe('FileUpload', () => {
  it('shows the resume banner and discard action for an issued session', async () => {
    const target = await render();
    expect(target.textContent).toContain('You have an unfinished upload');
    expect(target.textContent).toContain('Discard and start over');
  });

  it('shows the drop zone when there is no active session', async () => {
    fetchActiveUploadSession.mockResolvedValue({ session: null });
    const target = await render();
    expect(target.textContent).toContain('Drag and drop audio files here');
  });

  it('shows both partial-upload actions after a failed scheduler run', async () => {
    fetchActiveUploadSession.mockResolvedValue({ session: null });
    createUploadSession.mockResolvedValue({
      session_id: 'session-1',
      status: 'issued',
      expires_at: '2026-09-23T01:00:00Z',
      total_files: 1,
      total_bytes: 3,
      files: [{ file_id: 'file-1', original_filename: 'bird.wav', upload_url: '' }],
    });
    const target = await render();
    const file = new File([new Uint8Array([1, 2, 3])], 'bird.wav', { type: 'audio/wav' });
    const input = target.querySelector('input[type="file"]') as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [file] });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await tick();
    const uploadButton = Array.from(target.querySelectorAll('button')).find((button) => button.textContent?.includes('Upload'));
    uploadButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    await Promise.resolve();
    await tick();
    expect(target.textContent).toContain('Retry 1 file(s)');
    expect(target.textContent).toContain('Import without the 1 failed file(s)');
    const importButton = Array.from(target.querySelectorAll('button')).find((button) => button.textContent?.includes('Import without'));
    expect(importButton?.disabled).toBe(true);
  });

  it('shows incomplete files in partial state when completion remains issued', async () => {
    fetchActiveUploadSession.mockResolvedValue({ session: null });
    createUploadSession.mockResolvedValue({
      session_id: 'session-1',
      status: 'issued',
      expires_at: '2026-09-23T01:00:00Z',
      total_files: 1,
      total_bytes: 3,
      files: [{ file_id: 'file-1', original_filename: 'bird.wav', upload_url: '' }],
    });
    mockedScheduler.runImpl = async (fileId, cb) => {
      if (fileId) cb.onFileAcknowledged?.(fileId, 1);
      return { done: [], failed: [] };
    };
    completeUploadSession.mockResolvedValue({
      session_id: 'session-1',
      status: 'issued',
      verified_files: 0,
      missing_files: 1,
      mismatched_files: 0,
      skipped_files: 0,
    });
    const target = await render();
    const file = new File([new Uint8Array([1, 2, 3])], 'bird.wav', { type: 'audio/wav' });
    const input = target.querySelector('input[type="file"]') as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [file] });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await tick();
    const uploadButton = Array.from(target.querySelectorAll('button')).find((button) => button.textContent?.includes('Upload'));
    uploadButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    await Promise.resolve();
    await tick();
    await vi.waitFor(() => expect(target.textContent).toContain('Not fully transferred'));
    expect(target.textContent).toContain('Not fully transferred');
    expect(target.textContent).not.toContain('Processing');
  });

  it('does not auto-complete when a resumed server file was not selected', async () => {
    const resumed = {
      ...issuedSession,
      total_files: 2,
      total_bytes: 6,
      files: [
        issuedSession.files[0],
        { ...issuedSession.files[0], file_id: 'file-2', original_filename: 'frog.wav', received_bytes: 0 },
      ],
    };
    fetchActiveUploadSession.mockResolvedValue({ session: resumed });
    mockedScheduler.runImpl = async (fileId, cb) => {
      if (fileId) {
        cb.onFileAcknowledged?.(fileId, 3);
        cb.onFileDone(fileId);
      }
      return { done: fileId ? [fileId] : [], failed: [] };
    };
    completeUploadSession.mockResolvedValue({
      session_id: 'session-1',
      status: 'uploaded',
      verified_files: 1,
      missing_files: 0,
      mismatched_files: 0,
      skipped_files: 0,
    });
    const target = await render();
    const file = new File([new Uint8Array([1, 2, 3])], 'bird.wav', { type: 'audio/wav' });
    const input = target.querySelector('input[type="file"]') as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [file] });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await tick();
    await Promise.resolve();
    await tick();
    expect(target.textContent).toContain('Not selected');
    expect(target.textContent).toContain('Choose the missing files');
    expect(completeUploadSession).not.toHaveBeenCalled();
  });

  it('cancels the banner session when discarded', async () => {
    const target = await render();
    const discardButton = Array.from(target.querySelectorAll('button')).find((button) => button.textContent?.includes('Discard'));
    discardButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await tick();
    await Promise.resolve();
    expect(cancelUploadSession).toHaveBeenCalledWith('p', 'd', 'session-1');
  });

  it('starts only one scheduler for two rapid resume selections', async () => {
    fetchActiveUploadSession.mockResolvedValue({ session: issuedSession });
    mockedScheduler.runImpl = async (fileId, cb) => {
      if (fileId) {
        cb.onFileAcknowledged?.(fileId, 3);
        cb.onFileDone(fileId);
      }
      return { done: fileId ? [fileId] : [], failed: [] };
    };
    completeUploadSession.mockResolvedValue({
      session_id: 'session-1',
      status: 'uploaded',
      verified_files: 1,
      missing_files: 0,
      mismatched_files: 0,
      skipped_files: 0,
    });
    const target = await render();
    const firstFile = new File([new Uint8Array([1, 2, 3])], 'bird.wav', { type: 'audio/wav' });
    const secondFile = new File([new Uint8Array([1, 2, 3])], 'bird.wav', { type: 'audio/wav' });
    const input = target.querySelector('input[type="file"]') as HTMLInputElement;
    Object.defineProperty(input, 'files', { value: [firstFile], configurable: true });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    Object.defineProperty(input, 'files', { value: [secondFile], configurable: true });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await Promise.resolve();
    await Promise.resolve();
    await tick();
    expect(mockedScheduler.instanceCount).toBe(1);
  });
});
