import { describe, expect, it, vi } from 'vitest';
import type { UploadSessionStatusResponse } from '$lib/types/data';
import { planResume } from './resume';

function session(overrides: Partial<UploadSessionStatusResponse['files'][number]>[] = []): UploadSessionStatusResponse {
  return {
    session_id: 'session-1',
    status: 'issued',
    total_files: overrides.length,
    total_bytes: 4 * overrides.length,
    validated_files: 0,
    imported_files: 0,
    progress_percent: 0,
    error: null,
    created_at: '2026-09-23T00:00:00Z',
    updated_at: '2026-09-23T00:00:00Z',
    files: overrides.map((file, index) => ({
      file_id: `file-${index}`,
      original_filename: `file-${index}.wav`,
      declared_size: 4,
      received_bytes: 0,
      chunk_digests: [],
      status: 'pending',
      file_size: 4,
      duration: null,
      samplerate: null,
      channels: null,
      validation_error: null,
      recording_id: null,
      ...file,
    })),
  };
}

describe('planResume', () => {
  it('resumes exact matches at the server offset', async () => {
    const file = new File([new Uint8Array([1, 2, 3, 4])], 'birds.wav');
    const current = session([{
      original_filename: 'birds.wav',
      received_bytes: 4,
      chunk_digests: ['a', 'b'],
    }]);
    const hash = vi.fn()
      .mockResolvedValueOnce('a')
      .mockResolvedValueOnce('b');
    const plan = await planResume(current, [file], { chunkSize: 2, hash });
    expect(plan.matched[0]).toMatchObject({ fileId: 'file-0', startOffset: 4, file });
    expect(plan.needsRestart).toEqual([]);
    expect(hash).toHaveBeenCalledTimes(2);
  });

  it('restarts a match when a received chunk changed', async () => {
    const file = new File([new Uint8Array([1, 2, 3, 4])], 'birds.wav');
    const current = session([{
      original_filename: 'birds.wav',
      received_bytes: 4,
      chunk_digests: ['a', 'b'],
    }]);
    const plan = await planResume(current, [file], {
      chunkSize: 2,
      hash: vi.fn().mockResolvedValueOnce('different'),
    });
    expect(plan.matched[0]?.startOffset).toBe(0);
    expect(plan.needsRestart).toEqual(['file-0']);
  });

  it('reports unmatched server files and extra local files', async () => {
    const current = session([{
      original_filename: 'server-only.wav',
      received_bytes: 0,
    }]);
    const local = new File([new Uint8Array([1])], 'local-only.wav');
    const plan = await planResume(current, [local], { chunkSize: 2, hash: vi.fn() });
    expect(plan.matched).toEqual([]);
    expect(plan.unmatched).toHaveLength(1);
    expect(plan.alreadyComplete).toEqual([]);
    expect(plan.extra).toEqual([local]);
  });

  it('separates completed unmatched server files from files still needing selection', async () => {
    const current = session([
      {
        original_filename: 'complete-server-only.wav',
        received_bytes: 4,
      },
      {
        original_filename: 'incomplete-server-only.wav',
        received_bytes: 2,
      },
    ]);
    const plan = await planResume(current, [], { chunkSize: 2, hash: vi.fn() });
    expect(plan.alreadyComplete.map((file) => file.original_filename)).toEqual(['complete-server-only.wav']);
    expect(plan.unmatched.map((file) => file.original_filename)).toEqual(['incomplete-server-only.wav']);
  });

  it('restarts when hashing is unavailable', async () => {
    const file = new File([new Uint8Array([1, 2])], 'birds.wav');
    const current = session([{
      original_filename: 'birds.wav',
      declared_size: 2,
      received_bytes: 2,
      chunk_digests: ['digest'],
    }]);
    const plan = await planResume(current, [file], { chunkSize: 2, hash: vi.fn().mockResolvedValue(null) });
    expect(plan.matched[0]?.startOffset).toBe(0);
    expect(plan.needsRestart).toEqual(['file-0']);
  });
});
