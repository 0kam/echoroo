/**
 * Formatting helpers for Xeno-canto Creative Commons license values.
 *
 * Xeno-canto returns the license as a Creative Commons URL in its ``lic``
 * field, e.g. ``//creativecommons.org/licenses/by-nc-sa/4.0/``. These helpers
 * turn that raw value into a human-readable label (``CC BY-NC-SA 4.0``) and a
 * fully-qualified href so attribution can be shown compactly under a reference
 * recording player/card.
 */

/**
 * Normalize a Creative Commons license URL into an absolute ``https://`` href.
 *
 * Xeno-canto emits protocol-relative URLs (``//creativecommons.org/...``);
 * older values may already be absolute. Returns null when the value is not a
 * recognizable URL so callers can render the raw label without a link.
 */
export function licenseHref(license: string | undefined | null): string | null {
  if (!license) return null;
  const trimmed = license.trim();
  if (trimmed.startsWith('//')) return `https:${trimmed}`;
  if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) return trimmed;
  return null;
}

/**
 * Derive a short human label from a Creative Commons license URL.
 *
 * ``//creativecommons.org/licenses/by-nc-sa/4.0/`` -> ``CC BY-NC-SA 4.0``.
 * ``//creativecommons.org/publicdomain/zero/1.0/`` -> ``CC0 1.0``.
 * When the value is not a recognizable CC URL the trimmed original is returned
 * (so a plain label such as ``CC BY-NC 4.0`` passes through unchanged).
 */
export function formatLicenseLabel(license: string | undefined | null): string {
  if (!license) return '';
  const trimmed = license.trim();

  const pdMatch = trimmed.match(/creativecommons\.org\/publicdomain\/zero\/([\d.]+)/i);
  if (pdMatch?.[1]) return `CC0 ${pdMatch[1]}`;

  const ccMatch = trimmed.match(/creativecommons\.org\/licenses\/([a-z-]+)\/([\d.]+)/i);
  if (ccMatch?.[1] && ccMatch[2]) {
    return `CC ${ccMatch[1].toUpperCase()} ${ccMatch[2]}`;
  }

  return trimmed;
}
