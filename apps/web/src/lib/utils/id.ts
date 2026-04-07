/**
 * Generates a unique ID string that works in all browser environments,
 * including non-secure contexts (HTTP) where crypto.randomUUID() is unavailable.
 */
export function generateId(): string {
  return Math.random().toString(36).substring(2) + Date.now().toString(36);
}
