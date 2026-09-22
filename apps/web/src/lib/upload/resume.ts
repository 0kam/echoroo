import type { UploadFileStatusResponse, UploadSessionStatusResponse } from '$lib/types/data';
import type { PlannedFile } from './scheduler';

async function readBlob(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === 'function') return blob.arrayBuffer();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error ?? new Error('Unable to read file'));
    reader.readAsArrayBuffer(blob);
  });
}

export interface ResumePlan {
  matched: PlannedFile[];
  needsRestart: string[];
  unmatched: UploadFileStatusResponse[];
  extra: File[];
}

export async function planResume(
  session: UploadSessionStatusResponse,
  files: File[],
  opts: { chunkSize: number; hash: (b: ArrayBuffer) => Promise<string | null> },
): Promise<ResumePlan> {
  const matched: PlannedFile[] = [];
  const needsRestart: string[] = [];
  const unmatched: UploadFileStatusResponse[] = [];
  const usedLocalIndexes = new Set<number>();

  for (const serverFile of session.files) {
    const localIndex = files.findIndex(
      (file, index) =>
        !usedLocalIndexes.has(index) &&
        file.name === serverFile.original_filename &&
        file.size === serverFile.declared_size,
    );

    if (localIndex === -1) {
      unmatched.push(serverFile);
      continue;
    }

    usedLocalIndexes.add(localIndex);
    const localFile = files[localIndex];
    if (!localFile) continue;

    let canResume = serverFile.received_bytes === 0;
    if (serverFile.received_bytes > 0) {
      canResume = true;
      for (let offset = 0, digestIndex = 0; offset < serverFile.received_bytes; offset += opts.chunkSize, digestIndex += 1) {
        const chunkEnd = Math.min(offset + opts.chunkSize, serverFile.received_bytes);
        try {
          const digest = await opts.hash(await readBlob(localFile.slice(offset, chunkEnd)));
          if (digest === null || digest !== serverFile.chunk_digests[digestIndex]) {
            canResume = false;
            break;
          }
        } catch {
          canResume = false;
          break;
        }
      }
      if (canResume && Math.ceil(serverFile.received_bytes / opts.chunkSize) !== serverFile.chunk_digests.length) {
        canResume = false;
      }
    }

    const startOffset = canResume ? serverFile.received_bytes : 0;
    if (!canResume && serverFile.received_bytes > 0) needsRestart.push(serverFile.file_id);
    matched.push({
      fileId: serverFile.file_id,
      file: localFile,
      declaredSize: serverFile.declared_size,
      startOffset,
    });
  }

  const extra = files.filter((_file, index) => !usedLocalIndexes.has(index));
  return { matched, needsRestart, unmatched, extra };
}
