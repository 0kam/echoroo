/**
 * Setup API client
 * Handles initial setup and wizard-related operations
 */

import { apiClient } from './client';
import type {
  User,
  SetupStatusResponse,
  SetupInitializeRequest,
} from '$lib/types';

// Re-export types for convenience
export type { SetupStatusResponse, SetupInitializeRequest };

/**
 * Get current setup status
 * @returns Setup status indicating if setup is required/completed
 */
export async function getSetupStatus(): Promise<SetupStatusResponse> {
  return apiClient.get<SetupStatusResponse>('/api/setup/status');
}

/**
 * Initialize system setup by creating first admin user
 * @param data - Admin user credentials and info
 * @returns Created admin user
 */
export async function initializeSetup(data: SetupInitializeRequest): Promise<User> {
  return apiClient.post<User>('/api/setup/initialize', data);
}
