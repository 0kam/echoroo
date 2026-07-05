/**
 * CSV helpers for the bulk-invitation results export (T280 / T281).
 *
 * Kept as a pure module (no Svelte / DOM dependencies) so the escaping and
 * row-building logic can be unit tested in isolation. One-shot invitation
 * URLs are only ever copied to the clipboard by the caller — this module
 * merely serialises the transient result rows into CSV text.
 */
import type { BulkInvitationResultItem } from '$lib/types';

/**
 * RFC-4180-lite CSV field escaping: wrap in quotes and double internal
 * quotes when the field contains a comma, quote, or newline.
 */
export function csvEscape(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

/**
 * Build the bulk results CSV (`email,status,invitation_url`). The URL
 * column is empty for non-issued rows. `resolveUrl` turns the raw signed
 * token returned by the backend into the full, shareable URL.
 */
export function buildBulkCsv(
  results: BulkInvitationResultItem[],
  resolveUrl: (raw: string) => string,
): string {
  const header = 'email,status,invitation_url';
  const rows = results.map(
    (r) =>
      `${csvEscape(r.email)},${r.status},${csvEscape(
        r.invitation_url ? resolveUrl(r.invitation_url) : '',
      )}`,
  );
  return [header, ...rows].join('\n');
}
