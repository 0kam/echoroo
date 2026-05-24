/**
 * Detection export API client for downloading CSV and ML datasets.
 *
 * spec/009 PR 4: both endpoints go through ``/web-api/v1`` (cookie +
 * CSRF session boundary). These are GET requests — no CSRF header is
 * required.
 */

import { apiClient } from './client';

const WEB_API_BASE = '/web-api/v1';

/**
 * Build query string from export filter params.
 */
function buildExportParams(params?: {
  status?: string;
  tag_id?: string;
  dataset_id?: string;
  detection_run_id?: string;
}): string {
  if (!params) return '';
  const query = new URLSearchParams();
  if (params.status) query.set('status', params.status);
  if (params.tag_id) query.set('tag_id', params.tag_id);
  if (params.dataset_id) query.set('dataset_id', params.dataset_id);
  if (params.detection_run_id) query.set('detection_run_id', params.detection_run_id);
  const str = query.toString();
  return str ? `?${str}` : '';
}

/**
 * Export detections as CSV file (triggers browser download).
 */
export async function exportDetectionsCSV(
  projectId: string,
  params?: { status?: string; tag_id?: string; dataset_id?: string; detection_run_id?: string }
): Promise<void> {
  const qs = buildExportParams(params);
  const response = await apiClient.requestRaw(
    `${WEB_API_BASE}/projects/${projectId}/detections/export/csv${qs}`
  );
  if (!response.ok) {
    throw new Error(`Export failed: ${response.statusText}`);
  }
  const blob = await response.blob();
  downloadBlob(blob, 'detections.csv');
}

/**
 * Export ML training dataset as ZIP file (triggers browser download).
 */
export async function exportMLDataset(
  projectId: string,
  params?: { dataset_id?: string; detection_run_id?: string }
): Promise<void> {
  const qs = buildExportParams(params);
  const response = await apiClient.requestRaw(
    `${WEB_API_BASE}/projects/${projectId}/detections/export/ml-dataset${qs}`
  );
  if (!response.ok) {
    throw new Error(`Export failed: ${response.statusText}`);
  }
  const blob = await response.blob();
  downloadBlob(blob, 'ml-dataset.zip');
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
