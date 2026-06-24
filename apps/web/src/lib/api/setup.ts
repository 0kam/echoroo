/**
 * Setup API client
 * Handles initial setup and wizard-related operations
 */

import { apiClient } from './client';
import type {
  SetupCompleteResponse,
  SetupInitializeRequest,
} from '$lib/types';

// Re-export types for convenience
export type { SetupCompleteResponse, SetupInitializeRequest };

/**
 * Initialize system setup by creating first admin user
 * @param data - Admin user credentials and info
 * @returns Created admin user and one-time setup artifacts
 */
export async function initializeSetup(
  data: SetupInitializeRequest
): Promise<SetupCompleteResponse> {
  // W2-2-A: routed through the web_v1 BFF. Setup is unauthenticated and
  // CSRF-exempt (pre-session bootstrap), so no csrfHeaders are required.
  return apiClient.post<SetupCompleteResponse>('/web-api/v1/setup/initialize', data);
}
