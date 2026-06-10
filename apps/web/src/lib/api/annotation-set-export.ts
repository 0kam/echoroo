/**
 * Annotation-set export API client.
 *
 * Mirrors ``detection-export.ts``: a GET against the ``/web-api/v1`` cookie +
 * CSRF session boundary that streams a CamtrapDP observations CSV (one row per
 * TimeRangeAnnotation, with the FR-086 license columns and the segment /
 * recording offset columns). GET requests require no CSRF header.
 */

import { apiClient } from './client';

const WEB_API_BASE = '/web-api/v1';

/**
 * Export an annotation set's annotations as a CamtrapDP CSV file (triggers a
 * browser download).
 */
export async function exportAnnotationSetCsv(
  projectId: string,
  setId: string
): Promise<void> {
  const response = await apiClient.requestRaw(
    `${WEB_API_BASE}/projects/${projectId}/annotation-sets/${setId}/export/csv`
  );
  if (!response.ok) {
    throw new Error(`Export failed: ${response.statusText}`);
  }
  const blob = await response.blob();
  downloadBlob(blob, 'annotation-set.csv');
}

/**
 * Export an annotation set as a dataset ZIP (CSV labels + per-segment audio
 * clips) and trigger a browser download. The ZIP contains ``annotations.csv``,
 * ``segments.csv`` and one ``clips/<segment_id>.wav`` per finalized segment.
 */
export async function downloadAnnotationSetDataset(
  projectId: string,
  setId: string
): Promise<void> {
  const response = await apiClient.requestRaw(
    `${WEB_API_BASE}/projects/${projectId}/annotation-sets/${setId}/export/dataset`
  );
  if (!response.ok) {
    throw new Error(`Export failed: ${response.statusText}`);
  }
  const blob = await response.blob();
  downloadBlob(blob, `${setId}_dataset.zip`);
}

/**
 * Trigger a browser file download from a Blob.
 */
function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
